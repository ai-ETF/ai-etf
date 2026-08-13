export type Json =
  | string
  | number
  | boolean
  | null
  | { [key: string]: Json | undefined }
  | Json[]

export type Database = {
  // Allows to automatically instantiate createClient with right options
  // instead of createClient<Database, { PostgrestVersion: 'XX' }>(URL, KEY)
  __InternalSupabase: {
    PostgrestVersion: "13.0.5"
  }
  public: {
    Tables: {
      account_snapshots: {
        Row: {
          cash: number
          created_at: string | null
          id: string
          position_value: number
          snapshot_date: string
          total_assets: number
          total_pnl: number
          total_return_rate: number
          user_id: string
        }
        Insert: {
          cash: number
          created_at?: string | null
          id?: string
          position_value?: number
          snapshot_date: string
          total_assets: number
          total_pnl?: number
          total_return_rate?: number
          user_id: string
        }
        Update: {
          cash?: number
          created_at?: string | null
          id?: string
          position_value?: number
          snapshot_date?: string
          total_assets?: number
          total_pnl?: number
          total_return_rate?: number
          user_id?: string
        }
        Relationships: []
      }
      accounts: {
        Row: {
          auto_invest_enabled: boolean
          auto_invest_reserve: number
          cash: number
          created_at: string | null
          frozen_cash: number
          id: string
          updated_at: string | null
          user_id: string
        }
        Insert: {
          auto_invest_enabled?: boolean
          auto_invest_reserve?: number
          cash?: number
          created_at?: string | null
          frozen_cash?: number
          id?: string
          updated_at?: string | null
          user_id: string
        }
        Update: {
          auto_invest_enabled?: boolean
          auto_invest_reserve?: number
          cash?: number
          created_at?: string | null
          frozen_cash?: number
          id?: string
          updated_at?: string | null
          user_id?: string
        }
        Relationships: []
      }
      ai_requests: {
        Row: {
          created_at: string | null
          id: string
          metadata: Json | null
          prompt: string
          response: string | null
          status: string
          updated_at: string | null
        }
        Insert: {
          created_at?: string | null
          id?: string
          metadata?: Json | null
          prompt: string
          response?: string | null
          status?: string
          updated_at?: string | null
        }
        Update: {
          created_at?: string | null
          id?: string
          metadata?: Json | null
          prompt?: string
          response?: string | null
          status?: string
          updated_at?: string | null
        }
        Relationships: []
      }
      allocation_models: {
        Row: {
          config: Json
          created_at: string | null
          id: string
          version: string | null
        }
        Insert: {
          config: Json
          created_at?: string | null
          id?: string
          version?: string | null
        }
        Update: {
          config?: Json
          created_at?: string | null
          id?: string
          version?: string | null
        }
        Relationships: []
      }
      chats: {
        Row: {
          created_at: string | null
          id: string
          metadata: Json | null
          title: string | null
          updated_at: string | null
          user_id: string
        }
        Insert: {
          created_at?: string | null
          id?: string
          metadata?: Json | null
          title?: string | null
          updated_at?: string | null
          user_id: string
        }
        Update: {
          created_at?: string | null
          id?: string
          metadata?: Json | null
          title?: string | null
          updated_at?: string | null
          user_id?: string
        }
        Relationships: []
      }
      document_chunks: {
        Row: {
          chunk_index: number
          content: string
          created_at: string | null
          document_id: string
          document_type: string | null
          embedding: string | null
          id: string
          metadata: Json | null
          page_number: number | null
        }
        Insert: {
          chunk_index: number
          content: string
          created_at?: string | null
          document_id: string
          document_type?: string | null
          embedding?: string | null
          id?: string
          metadata?: Json | null
          page_number?: number | null
        }
        Update: {
          chunk_index?: number
          content?: string
          created_at?: string | null
          document_id?: string
          document_type?: string | null
          embedding?: string | null
          id?: string
          metadata?: Json | null
          page_number?: number | null
        }
        Relationships: [
          {
            foreignKeyName: "document_chunks_document_id_fkey"
            columns: ["document_id"]
            isOneToOne: false
            referencedRelation: "documents"
            referencedColumns: ["id"]
          },
        ]
      }
      documents: {
        Row: {
          created_at: string | null
          doc_type: string | null
          file_id: string
          id: string
          metadata: Json | null
          status: string
          title: string | null
          updated_at: string | null
          user_id: string
        }
        Insert: {
          created_at?: string | null
          doc_type?: string | null
          file_id: string
          id?: string
          metadata?: Json | null
          status: string
          title?: string | null
          updated_at?: string | null
          user_id: string
        }
        Update: {
          created_at?: string | null
          doc_type?: string | null
          file_id?: string
          id?: string
          metadata?: Json | null
          status?: string
          title?: string | null
          updated_at?: string | null
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "documents_file_id_fkey"
            columns: ["file_id"]
            isOneToOne: false
            referencedRelation: "files"
            referencedColumns: ["id"]
          },
        ]
      }
      files: {
        Row: {
          created_at: string | null
          id: string
          metadata: Json | null
          mime_type: string | null
          name: string
          parent_id: string | null
          size: number | null
          storage_path: string | null
          type: string
          updated_at: string | null
          user_id: string
        }
        Insert: {
          created_at?: string | null
          id?: string
          metadata?: Json | null
          mime_type?: string | null
          name: string
          parent_id?: string | null
          size?: number | null
          storage_path?: string | null
          type: string
          updated_at?: string | null
          user_id: string
        }
        Update: {
          created_at?: string | null
          id?: string
          metadata?: Json | null
          mime_type?: string | null
          name?: string
          parent_id?: string | null
          size?: number | null
          storage_path?: string | null
          type?: string
          updated_at?: string | null
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "files_parent_id_fkey"
            columns: ["parent_id"]
            isOneToOne: false
            referencedRelation: "files"
            referencedColumns: ["id"]
          },
        ]
      }
      fund_fee_rules: {
        Row: {
          commission_rate: number
          confirm_delay: number
          created_at: string | null
          custody_fee_rate: number
          fund_code: string
          fund_name: string
          fund_type: string
          id: string
          management_fee_rate: number
          min_purchase_amount: number
          purchase_fee_tiers: Json | null
          redeem_settle_delay: number
          redemption_fee_tiers: Json
          sales_service_fee_rate: number
          share_class: string
          updated_at: string | null
        }
        Insert: {
          commission_rate?: number
          confirm_delay?: number
          created_at?: string | null
          custody_fee_rate?: number
          fund_code: string
          fund_name: string
          fund_type?: string
          id?: string
          management_fee_rate?: number
          min_purchase_amount?: number
          purchase_fee_tiers?: Json | null
          redeem_settle_delay?: number
          redemption_fee_tiers?: Json
          sales_service_fee_rate?: number
          share_class?: string
          updated_at?: string | null
        }
        Update: {
          commission_rate?: number
          confirm_delay?: number
          created_at?: string | null
          custody_fee_rate?: number
          fund_code?: string
          fund_name?: string
          fund_type?: string
          id?: string
          management_fee_rate?: number
          min_purchase_amount?: number
          purchase_fee_tiers?: Json | null
          redeem_settle_delay?: number
          redemption_fee_tiers?: Json
          sales_service_fee_rate?: number
          share_class?: string
          updated_at?: string | null
        }
        Relationships: []
      }
      market_indicators: {
        Row: {
          as_of: string | null
          id: string
          indicator_type: string | null
          metadata: Json | null
          source: string | null
          symbol: string | null
          value: number | null
        }
        Insert: {
          as_of?: string | null
          id?: string
          indicator_type?: string | null
          metadata?: Json | null
          source?: string | null
          symbol?: string | null
          value?: number | null
        }
        Update: {
          as_of?: string | null
          id?: string
          indicator_type?: string | null
          metadata?: Json | null
          source?: string | null
          symbol?: string | null
          value?: number | null
        }
        Relationships: []
      }
      message_chunks: {
        Row: {
          chunk_id: string
          confidence: number | null
          id: string
          message_id: string
          metadata: Json | null
        }
        Insert: {
          chunk_id: string
          confidence?: number | null
          id?: string
          message_id: string
          metadata?: Json | null
        }
        Update: {
          chunk_id?: string
          confidence?: number | null
          id?: string
          message_id?: string
          metadata?: Json | null
        }
        Relationships: [
          {
            foreignKeyName: "message_chunks_chunk_id_fkey"
            columns: ["chunk_id"]
            isOneToOne: false
            referencedRelation: "document_chunks"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "message_chunks_message_id_fkey"
            columns: ["message_id"]
            isOneToOne: false
            referencedRelation: "messages"
            referencedColumns: ["id"]
          },
        ]
      }
      messages: {
        Row: {
          chat_id: string
          content: string
          created_at: string | null
          id: string
          metadata: Json | null
          role: string
          user_id: string | null
        }
        Insert: {
          chat_id: string
          content: string
          created_at?: string | null
          id?: string
          metadata?: Json | null
          role: string
          user_id?: string | null
        }
        Update: {
          chat_id?: string
          content?: string
          created_at?: string | null
          id?: string
          metadata?: Json | null
          role?: string
          user_id?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "messages_chat_id_fkey"
            columns: ["chat_id"]
            isOneToOne: false
            referencedRelation: "chats"
            referencedColumns: ["id"]
          },
        ]
      }
      positions: {
        Row: {
          available_date: string | null
          confirm_date: string | null
          cost_price: number
          created_at: string | null
          fund_code: string
          fund_name: string
          id: string
          quantity: number
          updated_at: string | null
          user_id: string
        }
        Insert: {
          available_date?: string | null
          confirm_date?: string | null
          cost_price?: number
          created_at?: string | null
          fund_code: string
          fund_name?: string
          id?: string
          quantity?: number
          updated_at?: string | null
          user_id: string
        }
        Update: {
          available_date?: string | null
          confirm_date?: string | null
          cost_price?: number
          created_at?: string | null
          fund_code?: string
          fund_name?: string
          id?: string
          quantity?: number
          updated_at?: string | null
          user_id?: string
        }
        Relationships: []
      }
      risk_questionnaires: {
        Row: {
          created_at: string | null
          id: string
          is_active: boolean | null
          questions: Json
          updated_at: string | null
          version: string
        }
        Insert: {
          created_at?: string | null
          id?: string
          is_active?: boolean | null
          questions: Json
          updated_at?: string | null
          version: string
        }
        Update: {
          created_at?: string | null
          id?: string
          is_active?: boolean | null
          questions?: Json
          updated_at?: string | null
          version?: string
        }
        Relationships: []
      }
      trade_flow: {
        Row: {
          amount: number
          direction: string
          fee: number
          fund_code: string
          fund_name: string
          id: string
          price: number
          quantity: number
          trade_pnl: number | null
          trade_time: string | null
          user_id: string
        }
        Insert: {
          amount: number
          direction: string
          fee?: number
          fund_code: string
          fund_name?: string
          id?: string
          price: number
          quantity: number
          trade_pnl?: number | null
          trade_time?: string | null
          user_id: string
        }
        Update: {
          amount?: number
          direction?: string
          fee?: number
          fund_code?: string
          fund_name?: string
          id?: string
          price?: number
          quantity?: number
          trade_pnl?: number | null
          trade_time?: string | null
          user_id?: string
        }
        Relationships: []
      }
      trade_orders: {
        Row: {
          amount: number
          confirm_date: string | null
          created_at: string | null
          direction: string
          fee: number
          fund_code: string
          fund_name: string
          fund_type: string | null
          id: string
          order_type: string
          price: number
          quantity: number
          reject_reason: string | null
          status: string
          updated_at: string | null
          user_id: string
        }
        Insert: {
          amount: number
          confirm_date?: string | null
          created_at?: string | null
          direction: string
          fee?: number
          fund_code: string
          fund_name?: string
          fund_type?: string | null
          id?: string
          order_type?: string
          price: number
          quantity: number
          reject_reason?: string | null
          status?: string
          updated_at?: string | null
          user_id: string
        }
        Update: {
          amount?: number
          confirm_date?: string | null
          created_at?: string | null
          direction?: string
          fee?: number
          fund_code?: string
          fund_name?: string
          fund_type?: string | null
          id?: string
          order_type?: string
          price?: number
          quantity?: number
          reject_reason?: string | null
          status?: string
          updated_at?: string | null
          user_id?: string
        }
        Relationships: []
      }
      user_allocations: {
        Row: {
          allocation: Json
          created_at: string | null
          id: string
          metadata: Json | null
          model_id: string
          over_allocated: boolean | null
          user_id: string
        }
        Insert: {
          allocation: Json
          created_at?: string | null
          id?: string
          metadata?: Json | null
          model_id: string
          over_allocated?: boolean | null
          user_id: string
        }
        Update: {
          allocation?: Json
          created_at?: string | null
          id?: string
          metadata?: Json | null
          model_id?: string
          over_allocated?: boolean | null
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "user_allocations_model_id_fkey"
            columns: ["model_id"]
            isOneToOne: false
            referencedRelation: "allocation_models"
            referencedColumns: ["id"]
          },
        ]
      }
      user_risk_answers: {
        Row: {
          answers: Json
          created_at: string | null
          id: string
          is_completed: boolean | null
          questionnaire_id: string
          session_id: string | null
          user_id: string
        }
        Insert: {
          answers: Json
          created_at?: string | null
          id?: string
          is_completed?: boolean | null
          questionnaire_id: string
          session_id?: string | null
          user_id: string
        }
        Update: {
          answers?: Json
          created_at?: string | null
          id?: string
          is_completed?: boolean | null
          questionnaire_id?: string
          session_id?: string | null
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "fk_user_answers_questionnaire"
            columns: ["questionnaire_id"]
            isOneToOne: false
            referencedRelation: "risk_questionnaires"
            referencedColumns: ["id"]
          },
        ]
      }
      user_risk_profiles: {
        Row: {
          ai_summary: Json | null
          answer_id: string | null
          confidence_score: number | null
          created_at: string | null
          dimension_scores: Json
          expires_at: string | null
          id: string
          is_active: boolean | null
          metadata: Json | null
          model_version: string
          risk_level: Database["public"]["Enums"]["risk_level"]
          source: Database["public"]["Enums"]["profile_source"]
          total_score: number | null
          user_id: string
          weighted_scores: Json | null
        }
        Insert: {
          ai_summary?: Json | null
          answer_id?: string | null
          confidence_score?: number | null
          created_at?: string | null
          dimension_scores?: Json
          expires_at?: string | null
          id?: string
          is_active?: boolean | null
          metadata?: Json | null
          model_version: string
          risk_level: Database["public"]["Enums"]["risk_level"]
          source: Database["public"]["Enums"]["profile_source"]
          total_score?: number | null
          user_id: string
          weighted_scores?: Json | null
        }
        Update: {
          ai_summary?: Json | null
          answer_id?: string | null
          confidence_score?: number | null
          created_at?: string | null
          dimension_scores?: Json
          expires_at?: string | null
          id?: string
          is_active?: boolean | null
          metadata?: Json | null
          model_version?: string
          risk_level?: Database["public"]["Enums"]["risk_level"]
          source?: Database["public"]["Enums"]["profile_source"]
          total_score?: number | null
          user_id?: string
          weighted_scores?: Json | null
        }
        Relationships: [
          {
            foreignKeyName: "fk_risk_profiles_answer"
            columns: ["answer_id"]
            isOneToOne: false
            referencedRelation: "user_risk_answers"
            referencedColumns: ["id"]
          },
        ]
      }
      watchlist: {
        Row: {
          created_at: string | null
          fund_code: string
          fund_name: string | null
          id: string
          sort_order: number | null
          updated_at: string | null
          user_id: string
        }
        Insert: {
          created_at?: string | null
          fund_code: string
          fund_name?: string | null
          id?: string
          sort_order?: number | null
          updated_at?: string | null
          user_id: string
        }
        Update: {
          created_at?: string | null
          fund_code?: string
          fund_name?: string | null
          id?: string
          sort_order?: number | null
          updated_at?: string | null
          user_id?: string
        }
        Relationships: []
      }
    }
    Views: {
      [_ in never]: never
    }
    Functions: {
      match_chunks: {
        Args: {
          document_id?: string
          match_count?: number
          query_embedding: string
        }
        Returns: {
          chunk_id: string
          chunk_index: number
          content: string
          document_id: string
          document_name: string
          document_type: string
          page_number: number
          similarity: number
        }[]
      }
      match_chunks_fts: {
        Args: { document_id?: string; match_count?: number; query_text: string }
        Returns: {
          chunk_id: string
          chunk_index: number
          content: string
          document_id: string
          document_name: string
          document_type: string
          fts_score: number
          keyword_hits: number
          page_number: number
        }[]
      }
    }
    Enums: {
      profile_source: "questionnaire" | "default" | "manual" | "system_inferred"
      risk_level: "conservative" | "moderate" | "aggressive"
    }
    CompositeTypes: {
      [_ in never]: never
    }
  }
}

type DatabaseWithoutInternals = Omit<Database, "__InternalSupabase">

type DefaultSchema = DatabaseWithoutInternals[Extract<keyof Database, "public">]

export type Tables<
  DefaultSchemaTableNameOrOptions extends
    | keyof (DefaultSchema["Tables"] & DefaultSchema["Views"])
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof (DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
        DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Views"])
    : never = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? (DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
      DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Views"])[TableName] extends {
      Row: infer R
    }
    ? R
    : never
  : DefaultSchemaTableNameOrOptions extends keyof (DefaultSchema["Tables"] &
        DefaultSchema["Views"])
    ? (DefaultSchema["Tables"] &
        DefaultSchema["Views"])[DefaultSchemaTableNameOrOptions] extends {
        Row: infer R
      }
      ? R
      : never
    : never

export type TablesInsert<
  DefaultSchemaTableNameOrOptions extends
    | keyof DefaultSchema["Tables"]
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
    : never = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"][TableName] extends {
      Insert: infer I
    }
    ? I
    : never
  : DefaultSchemaTableNameOrOptions extends keyof DefaultSchema["Tables"]
    ? DefaultSchema["Tables"][DefaultSchemaTableNameOrOptions] extends {
        Insert: infer I
      }
      ? I
      : never
    : never

export type TablesUpdate<
  DefaultSchemaTableNameOrOptions extends
    | keyof DefaultSchema["Tables"]
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
    : never = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"][TableName] extends {
      Update: infer U
    }
    ? U
    : never
  : DefaultSchemaTableNameOrOptions extends keyof DefaultSchema["Tables"]
    ? DefaultSchema["Tables"][DefaultSchemaTableNameOrOptions] extends {
        Update: infer U
      }
      ? U
      : never
    : never

export type Enums<
  DefaultSchemaEnumNameOrOptions extends
    | keyof DefaultSchema["Enums"]
    | { schema: keyof DatabaseWithoutInternals },
  EnumName extends DefaultSchemaEnumNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"]
    : never = never,
> = DefaultSchemaEnumNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"][EnumName]
  : DefaultSchemaEnumNameOrOptions extends keyof DefaultSchema["Enums"]
    ? DefaultSchema["Enums"][DefaultSchemaEnumNameOrOptions]
    : never

export type CompositeTypes<
  PublicCompositeTypeNameOrOptions extends
    | keyof DefaultSchema["CompositeTypes"]
    | { schema: keyof DatabaseWithoutInternals },
  CompositeTypeName extends PublicCompositeTypeNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[PublicCompositeTypeNameOrOptions["schema"]]["CompositeTypes"]
    : never = never,
> = PublicCompositeTypeNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[PublicCompositeTypeNameOrOptions["schema"]]["CompositeTypes"][CompositeTypeName]
  : PublicCompositeTypeNameOrOptions extends keyof DefaultSchema["CompositeTypes"]
    ? DefaultSchema["CompositeTypes"][PublicCompositeTypeNameOrOptions]
    : never

export const Constants = {
  public: {
    Enums: {
      profile_source: ["questionnaire", "default", "manual", "system_inferred"],
      risk_level: ["conservative", "moderate", "aggressive"],
    },
  },
} as const
