-- 用户风险画像表新增 risk_label 列（中文标签入库，避免运行时计算）
ALTER TABLE public.user_risk_profiles
  ADD COLUMN risk_label text;

-- 历史画像回填（risk_label 由 risk_level 枚举确定性映射）
UPDATE public.user_risk_profiles
SET risk_label = CASE risk_level::text
  WHEN 'conservative' THEN '保守型'
  WHEN 'moderate'     THEN '稳健型'
  WHEN 'aggressive'   THEN '进取型'
END
WHERE risk_label IS NULL;

COMMENT ON COLUMN public.user_risk_profiles.risk_label IS '用户风险等级中文标签：保守型/稳健型/进取型';
