-- 创建风险评估问卷表
CREATE TABLE IF NOT EXISTS risk_questionnaires (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    version TEXT NOT NULL,
    questions JSONB NOT NULL,
    is_active BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
-- 创建用户风险评估答案表
CREATE TABLE IF NOT EXISTS user_risk_answers (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID NOT NULL,
    questionnaire_id UUID REFERENCES risk_questionnaires(id),
    answers JSONB NOT NULL,
    session_id TEXT,
    is_completed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
-- 创建用户风险画像表
CREATE TABLE IF NOT EXISTS user_risk_profiles (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID NOT NULL,
    answer_id UUID REFERENCES user_risk_answers(id),
    risk_level TEXT CHECK (risk_level IN ('conservative', 'moderate', 'aggressive')),
    total_score NUMERIC,
    confidence_score NUMERIC DEFAULT 0.85,
    dimension_scores JSONB,
    weighted_scores JSONB,
    ai_summary JSONB,
    source TEXT CHECK (source IN ('questionnaire', 'default', 'manual', 'system_inferred')) DEFAULT 'default',
    model_version TEXT DEFAULT 'v1.0',
    is_active BOOLEAN DEFAULT TRUE,
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    expires_at TIMESTAMP WITH TIME ZONE
);
-- 创建更新时间触发器函数
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';
-- 为表添加更新时间触发器
CREATE TRIGGER update_risk_questionnaires_updated_at 
    BEFORE UPDATE ON risk_questionnaires 
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_user_risk_answers_updated_at 
    BEFORE UPDATE ON user_risk_answers 
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
-- 为user_risk_answers表添加用户ID索引
CREATE INDEX idx_user_risk_answers_user_id ON user_risk_answers(user_id);
CREATE INDEX idx_user_risk_answers_questionnaire_id ON user_risk_answers(questionnaire_id);
CREATE INDEX idx_user_risk_answers_created_at ON user_risk_answers(created_at);
-- 为user_risk_profiles表添加用户ID索引
CREATE INDEX idx_user_risk_profiles_user_id ON user_risk_profiles(user_id);
CREATE INDEX idx_user_risk_profiles_answer_id ON user_risk_profiles(answer_id);
CREATE INDEX idx_user_risk_profiles_created_at ON user_risk_profiles(created_at);
-- 为风险等级添加索引
CREATE INDEX idx_user_risk_profiles_risk_level ON user_risk_profiles(risk_level);
-- 为活跃状态添加索引
CREATE INDEX idx_user_risk_profiles_is_active ON user_risk_profiles(is_active);
-- 创建一个函数来激活新的风险画像并停用旧的
CREATE OR REPLACE FUNCTION activate_user_profile(p_user_id UUID, p_profile_data JSONB)
RETURNS UUID AS $$
DECLARE
    new_profile_id UUID;
BEGIN
    -- 停用该用户的所有现有风险画像
    UPDATE user_risk_profiles 
    SET is_active = false 
    WHERE user_id = p_user_id AND is_active = true;
    
    -- 创建新的风险画像
    INSERT INTO user_risk_profiles (user_id, risk_level, total_score, confidence_score, dimension_scores, 
                                   weighted_scores, ai_summary, source, model_version, is_active, metadata)
    VALUES (
        p_user_id,
        p_profile_data->>'risk_level',
        (p_profile_data->>'total_score')::NUMERIC,
        COALESCE((p_profile_data->>'confidence_score')::NUMERIC, 0.85),
        p_profile_data->'dimension_scores',
        p_profile_data->'weighted_scores',
        p_profile_data->'ai_summary',
        COALESCE(p_profile_data->>'source', 'questionnaire'),
        COALESCE(p_profile_data->>'model_version', 'v1.0'),
        true,
        p_profile_data->'metadata'
    )
    RETURNING id INTO new_profile_id;
    
    RETURN new_profile_id;
END;
$$ LANGUAGE plpgsql;
-- 为 Supabase Auth 用户创建 RLS 策略
ALTER TABLE risk_questionnaires ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_risk_answers ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_risk_profiles ENABLE ROW LEVEL SECURITY;
-- 为用户私有数据创建 RLS 策略
CREATE POLICY "Users can view own risk answers" ON user_risk_answers
    FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY "Users can insert own risk answers" ON user_risk_answers
    FOR INSERT WITH CHECK (auth.uid() = user_id);
CREATE POLICY "Users can view own risk profiles" ON user_risk_profiles
    FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY "Users can insert own risk profiles" ON user_risk_profiles
    FOR INSERT WITH CHECK (auth.uid() = user_id);
-- 问卷表允许所有人读取（因为需要公开获取活动问卷）
CREATE POLICY "Anyone can read questionnaires" ON risk_questionnaires
    FOR SELECT USING (true);
