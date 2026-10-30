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
  graphql_public: {
    Tables: {
      [_ in never]: never
    }
    Views: {
      [_ in never]: never
    }
    Functions: {
      graphql: {
        Args: {
          extensions?: Json
          operationName?: string
          query?: string
          variables?: Json
        }
        Returns: Json
      }
    }
    Enums: {
      [_ in never]: never
    }
    CompositeTypes: {
      [_ in never]: never
    }
  }
  public: {
    Tables: {
      account_snapshots: {
        Row: {
          cash: number
          created_at: string | null
          id: string
          position_value: number
          settling_cash: number
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
          settling_cash?: number
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
          settling_cash?: number
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
      confirm_runs: {
        Row: {
          confirmed: number
          duration_ms: number | null
          error: string | null
          finished_at: string | null
          heartbeat_at: string
          manual_review: number
          rejected: number
          retryable: number
          run_id: string
          scanned: number
          settled: number
          skipped_nav: number
          started_at: string
          status: string
          trigger_source: string
          worker: string
        }
        Insert: {
          confirmed?: number
          duration_ms?: number | null
          error?: string | null
          finished_at?: string | null
          heartbeat_at?: string
          manual_review?: number
          rejected?: number
          retryable?: number
          run_id?: string
          scanned?: number
          settled?: number
          skipped_nav?: number
          started_at?: string
          status: string
          trigger_source: string
          worker: string
        }
        Update: {
          confirmed?: number
          duration_ms?: number | null
          error?: string | null
          finished_at?: string | null
          heartbeat_at?: string
          manual_review?: number
          rejected?: number
          retryable?: number
          run_id?: string
          scanned?: number
          settled?: number
          skipped_nav?: number
          started_at?: string
          status?: string
          trigger_source?: string
          worker?: string
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
      fund: {
        Row: {
          establish_date: string | null
          first_seen_at: string
          ftype: string | null
          fund_code: string
          fund_manager: string | null
          fund_name: string
          is_qdii: boolean | null
          lifecycle_status: string
          manager_company: string | null
          metadata_source: string
          net_asset_scale: number | null
          qdii_reason: string | null
          risk_level_code: string | null
          synced_at: string | null
          tracking_index: string | null
          tracking_index_code: string | null
          updated_at: string
        }
        Insert: {
          establish_date?: string | null
          first_seen_at?: string
          ftype?: string | null
          fund_code: string
          fund_manager?: string | null
          fund_name: string
          is_qdii?: boolean | null
          lifecycle_status?: string
          manager_company?: string | null
          metadata_source: string
          net_asset_scale?: number | null
          qdii_reason?: string | null
          risk_level_code?: string | null
          synced_at?: string | null
          tracking_index?: string | null
          tracking_index_code?: string | null
          updated_at?: string
        }
        Update: {
          establish_date?: string | null
          first_seen_at?: string
          ftype?: string | null
          fund_code?: string
          fund_manager?: string | null
          fund_name?: string
          is_qdii?: boolean | null
          lifecycle_status?: string
          manager_company?: string | null
          metadata_source?: string
          net_asset_scale?: number | null
          qdii_reason?: string | null
          risk_level_code?: string | null
          synced_at?: string | null
          tracking_index?: string | null
          tracking_index_code?: string | null
          updated_at?: string
        }
        Relationships: []
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
          max_purchase_amount: number | null
          min_purchase_amount: number
          purchase_fee_tiers: Json | null
          redeem_settle_delay: number
          redemption_fee_tiers: Json
          sales_service_fee_rate: number
          share_class: string
          subscribe_status: string | null
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
          max_purchase_amount?: number | null
          min_purchase_amount?: number
          purchase_fee_tiers?: Json | null
          redeem_settle_delay?: number
          redemption_fee_tiers?: Json
          sales_service_fee_rate?: number
          share_class?: string
          subscribe_status?: string | null
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
          max_purchase_amount?: number | null
          min_purchase_amount?: number
          purchase_fee_tiers?: Json | null
          redeem_settle_delay?: number
          redemption_fee_tiers?: Json
          sales_service_fee_rate?: number
          share_class?: string
          subscribe_status?: string | null
          updated_at?: string | null
        }
        Relationships: []
      }
      fund_nav: {
        Row: {
          accumulated_nav: number | null
          daily_growth: number | null
          first_seen_at: string
          fund_code: string
          nav_date: string
          revision_count: number
          source: string
          unit_nav: number | null
          updated_at: string
        }
        Insert: {
          accumulated_nav?: number | null
          daily_growth?: number | null
          first_seen_at?: string
          fund_code: string
          nav_date: string
          revision_count?: number
          source: string
          unit_nav?: number | null
          updated_at?: string
        }
        Update: {
          accumulated_nav?: number | null
          daily_growth?: number | null
          first_seen_at?: string
          fund_code?: string
          nav_date?: string
          revision_count?: number
          source?: string
          unit_nav?: number | null
          updated_at?: string
        }
        Relationships: []
      }
      fund_nav_revision: {
        Row: {
          detected_at: string
          fund_code: string
          id: number
          nav_date: string
          new_accumulated_nav: number | null
          new_unit_nav: number | null
          old_accumulated_nav: number | null
          old_unit_nav: number | null
          source: string
        }
        Insert: {
          detected_at?: string
          fund_code: string
          id?: number
          nav_date: string
          new_accumulated_nav?: number | null
          new_unit_nav?: number | null
          old_accumulated_nav?: number | null
          old_unit_nav?: number | null
          source: string
        }
        Update: {
          detected_at?: string
          fund_code?: string
          id?: number
          nav_date?: string
          new_accumulated_nav?: number | null
          new_unit_nav?: number | null
          old_accumulated_nav?: number | null
          old_unit_nav?: number | null
          source?: string
        }
        Relationships: []
      }
      fund_nav_state: {
        Row: {
          fund_code: string
          history_start_date: string | null
          history_status: string
          last_checked_at: string | null
          last_error: string | null
          last_error_at: string | null
          last_success_at: string | null
          latest_nav_date: string | null
          latest_unit_nav: number | null
          updated_at: string
        }
        Insert: {
          fund_code: string
          history_start_date?: string | null
          history_status?: string
          last_checked_at?: string | null
          last_error?: string | null
          last_error_at?: string | null
          last_success_at?: string | null
          latest_nav_date?: string | null
          latest_unit_nav?: number | null
          updated_at?: string
        }
        Update: {
          fund_code?: string
          history_start_date?: string | null
          history_status?: string
          last_checked_at?: string | null
          last_error?: string | null
          last_error_at?: string | null
          last_success_at?: string | null
          latest_nav_date?: string | null
          latest_unit_nav?: number | null
          updated_at?: string
        }
        Relationships: []
      }
      fund_risk_profiles: {
        Row: {
          board_score: number
          breadth_score: number
          created_at: string | null
          fund_code: string
          id: string
          market_score: number
          risk_label: string
          risk_level: string
          updated_at: string | null
          volatility_score: number
        }
        Insert: {
          board_score: number
          breadth_score: number
          created_at?: string | null
          fund_code: string
          id?: string
          market_score: number
          risk_label: string
          risk_level: string
          updated_at?: string | null
          volatility_score: number
        }
        Update: {
          board_score?: number
          breadth_score?: number
          created_at?: string | null
          fund_code?: string
          id?: string
          market_score?: number
          risk_label?: string
          risk_level?: string
          updated_at?: string | null
          volatility_score?: number
        }
        Relationships: [
          {
            foreignKeyName: "fund_risk_profiles_fund_code_fkey"
            columns: ["fund_code"]
            isOneToOne: true
            referencedRelation: "fund"
            referencedColumns: ["fund_code"]
          },
          {
            foreignKeyName: "fund_risk_profiles_fund_code_fkey"
            columns: ["fund_code"]
            isOneToOne: true
            referencedRelation: "fund_catalog"
            referencedColumns: ["fund_code"]
          },
        ]
      }
      fund_trade_rule: {
        Row: {
          commission_rate: number
          confirm_delay: number
          created_at: string
          custody_fee_rate: number
          fund_code: string
          fund_type: string
          management_fee_rate: number
          max_purchase_amount: number | null
          min_purchase_amount: number
          purchase_fee_tiers: Json | null
          redeem_available_delay: number
          redeem_settle_delay: number
          redemption_fee_tiers: Json
          sales_service_fee_rate: number
          share_class: string
          subscribe_status: string | null
          updated_at: string
        }
        Insert: {
          commission_rate: number
          confirm_delay: number
          created_at?: string
          custody_fee_rate: number
          fund_code: string
          fund_type?: string
          management_fee_rate: number
          max_purchase_amount?: number | null
          min_purchase_amount: number
          purchase_fee_tiers?: Json | null
          redeem_available_delay?: number
          redeem_settle_delay: number
          redemption_fee_tiers: Json
          sales_service_fee_rate: number
          share_class: string
          subscribe_status?: string | null
          updated_at?: string
        }
        Update: {
          commission_rate?: number
          confirm_delay?: number
          created_at?: string
          custody_fee_rate?: number
          fund_code?: string
          fund_type?: string
          management_fee_rate?: number
          max_purchase_amount?: number | null
          min_purchase_amount?: number
          purchase_fee_tiers?: Json | null
          redeem_available_delay?: number
          redeem_settle_delay?: number
          redemption_fee_tiers?: Json
          sales_service_fee_rate?: number
          share_class?: string
          subscribe_status?: string | null
          updated_at?: string
        }
        Relationships: [
          {
            foreignKeyName: "fund_trade_rule_fund_code_fkey"
            columns: ["fund_code"]
            isOneToOne: true
            referencedRelation: "fund"
            referencedColumns: ["fund_code"]
          },
          {
            foreignKeyName: "fund_trade_rule_fund_code_fkey"
            columns: ["fund_code"]
            isOneToOne: true
            referencedRelation: "fund_catalog"
            referencedColumns: ["fund_code"]
          },
        ]
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
      position_lots: {
        Row: {
          available_date: string | null
          cost_price: number
          created_at: string
          fund_code: string
          fund_name: string
          id: string
          nav_date: string
          order_id: string | null
          quantity: number
          remaining_cost: number
          remaining_qty: number
          source: string
          source_ref: string | null
          updated_at: string
          user_id: string
        }
        Insert: {
          available_date?: string | null
          cost_price: number
          created_at?: string
          fund_code: string
          fund_name?: string
          id?: string
          nav_date: string
          order_id?: string | null
          quantity: number
          remaining_cost: number
          remaining_qty: number
          source: string
          source_ref?: string | null
          updated_at?: string
          user_id: string
        }
        Update: {
          available_date?: string | null
          cost_price?: number
          created_at?: string
          fund_code?: string
          fund_name?: string
          id?: string
          nav_date?: string
          order_id?: string | null
          quantity?: number
          remaining_cost?: number
          remaining_qty?: number
          source?: string
          source_ref?: string | null
          updated_at?: string
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "position_lots_order_id_fkey"
            columns: ["order_id"]
            isOneToOne: false
            referencedRelation: "trade_orders"
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
          principal: number
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
          principal?: number
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
          principal?: number
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
          order_id: string | null
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
          order_id?: string | null
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
          order_id?: string | null
          price?: number
          quantity?: number
          trade_pnl?: number | null
          trade_time?: string | null
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "trade_flow_order_id_fkey"
            columns: ["order_id"]
            isOneToOne: false
            referencedRelation: "trade_orders"
            referencedColumns: ["id"]
          },
        ]
      }
      trade_orders: {
        Row: {
          accepted_date: string | null
          amount: number
          attempt_count: number
          available_date: string | null
          client_order_id: string | null
          confirm_date: string | null
          created_at: string | null
          direction: string
          estimated_nav: number | null
          fee: number
          fee_rule_snapshot: Json | null
          fund_code: string
          fund_name: string
          fund_type: string | null
          id: string
          last_attempt_at: string | null
          last_error_code: string | null
          last_error_message: string | null
          net_amount: number | null
          order_type: string
          price: number
          processed_at: string | null
          processing_at: string | null
          processing_by: string | null
          quantity: number
          reject_reason: string | null
          settle_date: string | null
          settled_at: string | null
          status: string
          updated_at: string | null
          user_id: string
        }
        Insert: {
          accepted_date?: string | null
          amount: number
          attempt_count?: number
          available_date?: string | null
          client_order_id?: string | null
          confirm_date?: string | null
          created_at?: string | null
          direction: string
          estimated_nav?: number | null
          fee?: number
          fee_rule_snapshot?: Json | null
          fund_code: string
          fund_name?: string
          fund_type?: string | null
          id?: string
          last_attempt_at?: string | null
          last_error_code?: string | null
          last_error_message?: string | null
          net_amount?: number | null
          order_type?: string
          price: number
          processed_at?: string | null
          processing_at?: string | null
          processing_by?: string | null
          quantity: number
          reject_reason?: string | null
          settle_date?: string | null
          settled_at?: string | null
          status?: string
          updated_at?: string | null
          user_id: string
        }
        Update: {
          accepted_date?: string | null
          amount?: number
          attempt_count?: number
          available_date?: string | null
          client_order_id?: string | null
          confirm_date?: string | null
          created_at?: string | null
          direction?: string
          estimated_nav?: number | null
          fee?: number
          fee_rule_snapshot?: Json | null
          fund_code?: string
          fund_name?: string
          fund_type?: string | null
          id?: string
          last_attempt_at?: string | null
          last_error_code?: string | null
          last_error_message?: string | null
          net_amount?: number | null
          order_type?: string
          price?: number
          processed_at?: string | null
          processing_at?: string | null
          processing_by?: string | null
          quantity?: number
          reject_reason?: string | null
          settle_date?: string | null
          settled_at?: string | null
          status?: string
          updated_at?: string | null
          user_id?: string
        }
        Relationships: []
      }
      trading_calendar: {
        Row: {
          is_trading_day: boolean
          source: string
          trade_date: string
          updated_at: string
        }
        Insert: {
          is_trading_day: boolean
          source: string
          trade_date: string
          updated_at?: string
        }
        Update: {
          is_trading_day?: boolean
          source?: string
          trade_date?: string
          updated_at?: string
        }
        Relationships: []
      }
      trading_calendar_state: {
        Row: {
          coverage_end: string | null
          coverage_start: string | null
          id: boolean
          last_error: string | null
          last_error_at: string | null
          last_success_at: string | null
          updated_at: string
        }
        Insert: {
          coverage_end?: string | null
          coverage_start?: string | null
          id?: boolean
          last_error?: string | null
          last_error_at?: string | null
          last_success_at?: string | null
          updated_at?: string
        }
        Update: {
          coverage_end?: string | null
          coverage_start?: string | null
          id?: boolean
          last_error?: string | null
          last_error_at?: string | null
          last_success_at?: string | null
          updated_at?: string
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
          risk_label: string | null
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
          risk_label?: string | null
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
          risk_label?: string | null
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
      fund_catalog: {
        Row: {
          commission_rate: number | null
          confirm_delay: number | null
          custody_fee_rate: number | null
          establish_date: string | null
          ftype: string | null
          fund_code: string | null
          fund_manager: string | null
          fund_name: string | null
          fund_type: string | null
          is_qdii: boolean | null
          lifecycle_status: string | null
          management_fee_rate: number | null
          manager_company: string | null
          max_purchase_amount: number | null
          min_purchase_amount: number | null
          net_asset_scale: number | null
          purchase_fee_tiers: Json | null
          qdii_reason: string | null
          redeem_available_delay: number | null
          redeem_settle_delay: number | null
          redemption_fee_tiers: Json | null
          risk_level_code: string | null
          sales_service_fee_rate: number | null
          share_class: string | null
          subscribe_status: string | null
          tracking_index: string | null
          tracking_index_code: string | null
        }
        Relationships: []
      }
    }
    Functions: {
      acquire_confirm_run: {
        Args: { p_lease_seconds?: number; p_trigger: string; p_worker: string }
        Returns: string
      }
      confirm_buy_order: {
        Args: {
          p_fee: number
          p_lease_seconds?: number
          p_nav: number
          p_net_amount: number
          p_order_id: string
          p_quantity: number
          p_residual: number
          p_worker: string
        }
        Returns: Json
      }
      confirm_sell_order: {
        Args: {
          p_lease_seconds?: number
          p_nav: number
          p_order_id: string
          p_plan: Json
          p_worker: string
        }
        Returns: Json
      }
      credit_money_fund_income_atomic: {
        Args: {
          p_fund_code: string
          p_income: number
          p_income_date: string
          p_user_id: string
        }
        Returns: Json
      }
      delete_auth_user: { Args: { p_user_id: string }; Returns: undefined }
      finish_confirm_run: {
        Args: {
          p_counts: Json
          p_error?: string
          p_run_id: string
          p_status: string
        }
        Returns: undefined
      }
      heartbeat_confirm_run: { Args: { p_run_id: string }; Returns: undefined }
      mark_order_manual_review: {
        Args: {
          p_code: string
          p_message: string
          p_order_id: string
          p_worker: string
        }
        Returns: Json
      }
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
      merge_fund_nav: {
        Args: { rows: Json }
        Returns: {
          inserted: number
          revised: number
          updated: number
        }[]
      }
      place_purchase_order: {
        Args: {
          p_accepted_date: string
          p_amount: number
          p_available_date: string
          p_client_order_id?: string
          p_confirm_date: string
          p_estimated_nav: number
          p_fee: number
          p_fee_snapshot: Json
          p_fund_code: string
          p_fund_name: string
          p_max_purchase_amount?: number
          p_net_amount: number
          p_user_id: string
        }
        Returns: Json
      }
      place_redeem_order: {
        Args: {
          p_accepted_date: string
          p_client_order_id?: string
          p_confirm_date: string
          p_fee_snapshot: Json
          p_fund_code: string
          p_fund_name: string
          p_quantity: number
          p_settle_date: string
          p_user_id: string
        }
        Returns: Json
      }
      purge_user_data: { Args: { p_user_id: string }; Returns: undefined }
      reap_stale_processing: {
        Args: { p_lease_seconds?: number; p_max_attempts?: number }
        Returns: Json
      }
      recalc_position_from_lots: {
        Args: { p_fund_code: string; p_user_id: string }
        Returns: undefined
      }
      reconcile_orders: { Args: never; Returns: Json }
      reject_trade_order: {
        Args: {
          p_code: string
          p_lease_seconds?: number
          p_message: string
          p_order_id: string
          p_worker: string
        }
        Returns: Json
      }
      replace_trading_calendar: {
        Args: { p_source: string; p_trading_days: string[] }
        Returns: Json
      }
      requeue_manual_review_order: {
        Args: { p_admin: string; p_order_id: string; p_reason: string }
        Returns: Json
      }
      settle_redeem_order: {
        Args: { p_order_id: string; p_today: string; p_worker: string }
        Returns: Json
      }
      upsert_fund_catalog: {
        Args: { funds: Json; risk_profiles: Json; trade_rules: Json }
        Returns: {
          funds_written: number
          risk_written: number
          rules_written: number
        }[]
      }
      upsert_fund_nav_state: {
        Args: {
          p_error?: string
          p_fund_code: string
          p_got_data?: boolean
          p_history_start_date?: string
          p_history_status?: string
          p_latest_nav_date?: string
          p_latest_unit_nav?: number
        }
        Returns: undefined
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
  TableName extends (DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof (DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
        DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Views"])
    : never) = never,
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
  TableName extends (DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
    : never) = never,
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
  TableName extends (DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
    : never) = never,
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
  EnumName extends (DefaultSchemaEnumNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"]
    : never) = never,
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
  CompositeTypeName extends (PublicCompositeTypeNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[PublicCompositeTypeNameOrOptions["schema"]]["CompositeTypes"]
    : never) = never,
> = PublicCompositeTypeNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[PublicCompositeTypeNameOrOptions["schema"]]["CompositeTypes"][CompositeTypeName]
  : PublicCompositeTypeNameOrOptions extends keyof DefaultSchema["CompositeTypes"]
    ? DefaultSchema["CompositeTypes"][PublicCompositeTypeNameOrOptions]
    : never

export const Constants = {
  graphql_public: {
    Enums: {},
  },
  public: {
    Enums: {
      profile_source: ["questionnaire", "default", "manual", "system_inferred"],
      risk_level: ["conservative", "moderate", "aggressive"],
    },
  },
} as const
