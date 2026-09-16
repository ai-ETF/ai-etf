drop extension if exists "pg_net";
create extension if not exists "vector" with schema "public";
create type "public"."profile_source" as enum ('questionnaire', 'default', 'manual', 'system_inferred');
create type "public"."risk_level" as enum ('conservative', 'moderate', 'aggressive');
drop trigger if exists "update_risk_questionnaires_updated_at" on "public"."risk_questionnaires";
drop trigger if exists "update_user_risk_answers_updated_at" on "public"."user_risk_answers";
drop policy "Anyone can read questionnaires" on "public"."risk_questionnaires";
drop policy "Users can insert own risk answers" on "public"."user_risk_answers";
drop policy "Users can view own risk answers" on "public"."user_risk_answers";
drop policy "Users can insert own risk profiles" on "public"."user_risk_profiles";
drop policy "Users can view own risk profiles" on "public"."user_risk_profiles";
alter table "public"."user_risk_answers" drop constraint "user_risk_answers_questionnaire_id_fkey";
alter table "public"."user_risk_profiles" drop constraint "user_risk_profiles_answer_id_fkey";
alter table "public"."user_risk_profiles" drop constraint "user_risk_profiles_risk_level_check";
alter table "public"."user_risk_profiles" drop constraint "user_risk_profiles_source_check";
drop function if exists "public"."activate_user_profile"(p_user_id uuid, p_profile_data jsonb);
drop function if exists "public"."update_updated_at_column"();
drop index if exists "public"."idx_user_risk_answers_created_at";
drop index if exists "public"."idx_user_risk_answers_questionnaire_id";
drop index if exists "public"."idx_user_risk_answers_user_id";
drop index if exists "public"."idx_user_risk_profiles_answer_id";
drop index if exists "public"."idx_user_risk_profiles_created_at";
drop index if exists "public"."idx_user_risk_profiles_is_active";
drop index if exists "public"."idx_user_risk_profiles_risk_level";
drop index if exists "public"."idx_user_risk_profiles_user_id";
create table "public"."allocation_models" (
    "id" uuid not null default gen_random_uuid(),
    "version" text,
    "config" jsonb not null,
    "created_at" timestamp with time zone default now()
      );
create table "public"."chats" (
    "id" uuid not null default gen_random_uuid(),
    "user_id" uuid not null,
    "title" text,
    "metadata" jsonb default '{}'::jsonb,
    "created_at" timestamp with time zone default now(),
    "updated_at" timestamp with time zone default now()
      );
alter table "public"."chats" enable row level security;
create table "public"."document_chunks" (
    "id" uuid not null default gen_random_uuid(),
    "document_id" uuid not null,
    "chunk_index" integer not null,
    "content" text not null,
    "embedding" public.vector(1536),
    "page_number" integer,
    "metadata" jsonb default '{}'::jsonb,
    "created_at" timestamp with time zone default now()
      );
create table "public"."documents" (
    "id" uuid not null default gen_random_uuid(),
    "file_id" uuid not null,
    "user_id" uuid not null,
    "status" text not null,
    "title" text,
    "doc_type" text,
    "metadata" jsonb default '{}'::jsonb,
    "created_at" timestamp with time zone default now(),
    "updated_at" timestamp with time zone default now()
      );
alter table "public"."documents" enable row level security;
create table "public"."files" (
    "id" uuid not null default gen_random_uuid(),
    "user_id" uuid not null,
    "name" text not null,
    "type" text not null,
    "parent_id" uuid,
    "storage_path" text,
    "mime_type" text,
    "size" bigint,
    "metadata" jsonb default '{}'::jsonb,
    "created_at" timestamp with time zone default now(),
    "updated_at" timestamp with time zone default now()
      );
alter table "public"."files" enable row level security;
create table "public"."market_indicators" (
    "id" uuid not null default gen_random_uuid(),
    "symbol" text,
    "indicator_type" text,
    "value" numeric,
    "as_of" date,
    "source" text,
    "metadata" jsonb default '{}'::jsonb
      );
create table "public"."message_chunks" (
    "id" uuid not null default gen_random_uuid(),
    "message_id" uuid not null,
    "chunk_id" uuid not null,
    "confidence" numeric(5,4),
    "metadata" jsonb default '{}'::jsonb
      );
create table "public"."messages" (
    "id" uuid not null default gen_random_uuid(),
    "chat_id" uuid not null,
    "user_id" uuid,
    "role" text not null,
    "content" text not null,
    "metadata" jsonb default '{}'::jsonb,
    "created_at" timestamp with time zone default now()
      );
create table "public"."user_allocations" (
    "id" uuid not null default gen_random_uuid(),
    "user_id" uuid not null,
    "model_id" uuid not null,
    "allocation" jsonb not null,
    "over_allocated" boolean,
    "metadata" jsonb default '{}'::jsonb,
    "created_at" timestamp with time zone default now()
      );
alter table "public"."risk_questionnaires" alter column "is_active" set default true;
alter table "public"."risk_questionnaires" disable row level security;
alter table "public"."user_risk_answers" drop column "updated_at";
alter table "public"."user_risk_answers" alter column "is_completed" set default true;
alter table "public"."user_risk_answers" alter column "questionnaire_id" set not null;
alter table "public"."user_risk_answers" disable row level security;
alter table "public"."user_risk_profiles" alter column "confidence_score" drop default;
alter table "public"."user_risk_profiles" alter column "confidence_score" set data type numeric(3,2) using "confidence_score"::numeric(3,2);
alter table "public"."user_risk_profiles" alter column "dimension_scores" set default '{}'::jsonb;
alter table "public"."user_risk_profiles" alter column "dimension_scores" set not null;
alter table "public"."user_risk_profiles" alter column "metadata" set default '{}'::jsonb;
alter table "public"."user_risk_profiles" alter column "model_version" drop default;
alter table "public"."user_risk_profiles" alter column "model_version" set not null;
alter table "public"."user_risk_profiles" alter column "risk_level" set not null;
alter table "public"."user_risk_profiles" alter column "risk_level" set data type public.risk_level using "risk_level"::public.risk_level;
alter table "public"."user_risk_profiles" alter column "source" drop default;
alter table "public"."user_risk_profiles" alter column "source" set not null;
alter table "public"."user_risk_profiles" alter column "source" set data type public.profile_source using "source"::public.profile_source;
alter table "public"."user_risk_profiles" alter column "total_score" set data type numeric(3,2) using "total_score"::numeric(3,2);
alter table "public"."user_risk_profiles" alter column "weighted_scores" set default '{}'::jsonb;
alter table "public"."user_risk_profiles" disable row level security;
CREATE UNIQUE INDEX allocation_models_pkey ON public.allocation_models USING btree (id);
CREATE UNIQUE INDEX chats_pkey ON public.chats USING btree (id);
CREATE UNIQUE INDEX document_chunks_pkey ON public.document_chunks USING btree (id);
CREATE UNIQUE INDEX documents_pkey ON public.documents USING btree (id);
CREATE UNIQUE INDEX files_pkey ON public.files USING btree (id);
CREATE INDEX idx_chunks_document_id ON public.document_chunks USING btree (document_id);
CREATE INDEX idx_chunks_embedding ON public.document_chunks USING ivfflat (embedding public.vector_cosine_ops);
CREATE INDEX idx_documents_file_id ON public.documents USING btree (file_id);
CREATE INDEX idx_documents_status ON public.documents USING btree (status);
CREATE INDEX idx_documents_user_id ON public.documents USING btree (user_id);
CREATE INDEX idx_files_parent_id ON public.files USING btree (parent_id);
CREATE INDEX idx_files_type ON public.files USING btree (type);
CREATE INDEX idx_files_user_id ON public.files USING btree (user_id);
CREATE INDEX idx_message_chunks_chunk_id ON public.message_chunks USING btree (chunk_id);
CREATE INDEX idx_message_chunks_message_id ON public.message_chunks USING btree (message_id);
CREATE INDEX idx_messages_chat_id ON public.messages USING btree (chat_id);
CREATE INDEX idx_messages_created_at ON public.messages USING btree (created_at);
CREATE INDEX idx_questionnaires_active ON public.risk_questionnaires USING btree (is_active, version);
CREATE INDEX idx_risk_profiles_user_active ON public.user_risk_profiles USING btree (user_id, is_active);
CREATE INDEX idx_user_answers_questionnaire ON public.user_risk_answers USING btree (questionnaire_id);
CREATE INDEX idx_user_answers_user ON public.user_risk_answers USING btree (user_id);
CREATE UNIQUE INDEX market_indicators_pkey ON public.market_indicators USING btree (id);
CREATE UNIQUE INDEX message_chunks_pkey ON public.message_chunks USING btree (id);
CREATE UNIQUE INDEX messages_pkey ON public.messages USING btree (id);
CREATE UNIQUE INDEX uniq_active_profile_per_user ON public.user_risk_profiles USING btree (user_id) WHERE (is_active = true);
CREATE UNIQUE INDEX uniq_questionnaires_version ON public.risk_questionnaires USING btree (version);
CREATE UNIQUE INDEX uniq_user_questionnaire ON public.user_risk_answers USING btree (user_id, questionnaire_id);
CREATE UNIQUE INDEX user_allocations_pkey ON public.user_allocations USING btree (id);
alter table "public"."allocation_models" add constraint "allocation_models_pkey" PRIMARY KEY using index "allocation_models_pkey";
alter table "public"."chats" add constraint "chats_pkey" PRIMARY KEY using index "chats_pkey";
alter table "public"."document_chunks" add constraint "document_chunks_pkey" PRIMARY KEY using index "document_chunks_pkey";
alter table "public"."documents" add constraint "documents_pkey" PRIMARY KEY using index "documents_pkey";
alter table "public"."files" add constraint "files_pkey" PRIMARY KEY using index "files_pkey";
alter table "public"."market_indicators" add constraint "market_indicators_pkey" PRIMARY KEY using index "market_indicators_pkey";
alter table "public"."message_chunks" add constraint "message_chunks_pkey" PRIMARY KEY using index "message_chunks_pkey";
alter table "public"."messages" add constraint "messages_pkey" PRIMARY KEY using index "messages_pkey";
alter table "public"."user_allocations" add constraint "user_allocations_pkey" PRIMARY KEY using index "user_allocations_pkey";
alter table "public"."chats" add constraint "chats_user_id_fkey" FOREIGN KEY (user_id) REFERENCES auth.users(id) not valid;
alter table "public"."chats" validate constraint "chats_user_id_fkey";
alter table "public"."document_chunks" add constraint "document_chunks_document_id_fkey" FOREIGN KEY (document_id) REFERENCES public.documents(id) ON DELETE CASCADE not valid;
alter table "public"."document_chunks" validate constraint "document_chunks_document_id_fkey";
alter table "public"."documents" add constraint "documents_file_id_fkey" FOREIGN KEY (file_id) REFERENCES public.files(id) ON DELETE CASCADE not valid;
alter table "public"."documents" validate constraint "documents_file_id_fkey";
alter table "public"."documents" add constraint "documents_status_check" CHECK ((status = ANY (ARRAY['processing'::text, 'ready'::text, 'failed'::text]))) not valid;
alter table "public"."documents" validate constraint "documents_status_check";
alter table "public"."documents" add constraint "documents_user_id_fkey" FOREIGN KEY (user_id) REFERENCES auth.users(id) not valid;
alter table "public"."documents" validate constraint "documents_user_id_fkey";
alter table "public"."files" add constraint "files_parent_id_fkey" FOREIGN KEY (parent_id) REFERENCES public.files(id) not valid;
alter table "public"."files" validate constraint "files_parent_id_fkey";
alter table "public"."files" add constraint "files_type_check" CHECK ((type = ANY (ARRAY['folder'::text, 'file'::text]))) not valid;
alter table "public"."files" validate constraint "files_type_check";
alter table "public"."files" add constraint "files_user_id_fkey" FOREIGN KEY (user_id) REFERENCES auth.users(id) not valid;
alter table "public"."files" validate constraint "files_user_id_fkey";
alter table "public"."message_chunks" add constraint "message_chunks_chunk_id_fkey" FOREIGN KEY (chunk_id) REFERENCES public.document_chunks(id) not valid;
alter table "public"."message_chunks" validate constraint "message_chunks_chunk_id_fkey";
alter table "public"."message_chunks" add constraint "message_chunks_message_id_fkey" FOREIGN KEY (message_id) REFERENCES public.messages(id) ON DELETE CASCADE not valid;
alter table "public"."message_chunks" validate constraint "message_chunks_message_id_fkey";
alter table "public"."messages" add constraint "messages_chat_id_fkey" FOREIGN KEY (chat_id) REFERENCES public.chats(id) ON DELETE CASCADE not valid;
alter table "public"."messages" validate constraint "messages_chat_id_fkey";
alter table "public"."messages" add constraint "messages_role_check" CHECK ((role = ANY (ARRAY['user'::text, 'assistant'::text, 'system'::text]))) not valid;
alter table "public"."messages" validate constraint "messages_role_check";
alter table "public"."messages" add constraint "messages_user_id_fkey" FOREIGN KEY (user_id) REFERENCES auth.users(id) not valid;
alter table "public"."messages" validate constraint "messages_user_id_fkey";
alter table "public"."risk_questionnaires" add constraint "chk_questions_array" CHECK (((jsonb_typeof(questions) = 'array'::text) AND (jsonb_array_length(questions) > 0))) not valid;
alter table "public"."risk_questionnaires" validate constraint "chk_questions_array";
alter table "public"."user_allocations" add constraint "user_allocations_model_id_fkey" FOREIGN KEY (model_id) REFERENCES public.allocation_models(id) not valid;
alter table "public"."user_allocations" validate constraint "user_allocations_model_id_fkey";
alter table "public"."user_allocations" add constraint "user_allocations_user_id_fkey" FOREIGN KEY (user_id) REFERENCES auth.users(id) not valid;
alter table "public"."user_allocations" validate constraint "user_allocations_user_id_fkey";
alter table "public"."user_risk_answers" add constraint "chk_answers_object" CHECK ((jsonb_typeof(answers) = 'object'::text)) not valid;
alter table "public"."user_risk_answers" validate constraint "chk_answers_object";
alter table "public"."user_risk_answers" add constraint "fk_user_answers_questionnaire" FOREIGN KEY (questionnaire_id) REFERENCES public.risk_questionnaires(id) not valid;
alter table "public"."user_risk_answers" validate constraint "fk_user_answers_questionnaire";
alter table "public"."user_risk_answers" add constraint "uniq_user_questionnaire" UNIQUE using index "uniq_user_questionnaire";
alter table "public"."user_risk_answers" add constraint "user_risk_answers_user_id_fkey" FOREIGN KEY (user_id) REFERENCES auth.users(id) ON UPDATE RESTRICT not valid;
alter table "public"."user_risk_answers" validate constraint "user_risk_answers_user_id_fkey";
alter table "public"."user_risk_profiles" add constraint "chk_confidence_score_range" CHECK (((confidence_score IS NULL) OR ((confidence_score >= (0)::numeric) AND (confidence_score <= (1)::numeric)))) not valid;
alter table "public"."user_risk_profiles" validate constraint "chk_confidence_score_range";
alter table "public"."user_risk_profiles" add constraint "fk_risk_profiles_answer" FOREIGN KEY (answer_id) REFERENCES public.user_risk_answers(id) not valid;
alter table "public"."user_risk_profiles" validate constraint "fk_risk_profiles_answer";
alter table "public"."user_risk_profiles" add constraint "user_risk_profiles_user_id_fkey" FOREIGN KEY (user_id) REFERENCES auth.users(id) ON UPDATE RESTRICT not valid;
alter table "public"."user_risk_profiles" validate constraint "user_risk_profiles_user_id_fkey";
set check_function_bodies = off;
CREATE OR REPLACE FUNCTION public.check_parent_is_folder()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
begin
  if new.parent_id is not null then
    if (select type from files where id = new.parent_id) != 'folder' then
      raise exception 'Parent must be a folder';
    end if;
  end if;
  return new;
end;
$function$;
CREATE OR REPLACE FUNCTION public.delete_chat_messages()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
BEGIN
  -- 当 chats 表中的一行被删除时，OLD 代表被删除的那行数据
  -- 删除 messages 表中所有 chat_id 等于被删除会话 id 的记录
  DELETE FROM public.messages WHERE chat_id = OLD.id;
  -- 触发器函数需要返回被操作的行记录
  RETURN OLD;
END;
$function$;
CREATE OR REPLACE FUNCTION public.delete_storage_object()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
begin
  if old.type = 'file' then
    perform
      storage.delete_object('user-files', old.storage_path);
  end if;
  return old;
end;
$function$;
CREATE OR REPLACE FUNCTION public.match_chunks(query_embedding public.vector, match_count integer, document_id uuid DEFAULT NULL::uuid)
 RETURNS TABLE(chunk_id uuid, content text, similarity double precision, page_number integer, chunk_index integer)
 LANGUAGE sql
AS $function$
  select
    id as chunk_id,
    content,
    1 - (embedding <=> query_embedding) as similarity,
    page_number,
    chunk_index
  from document_chunks
  where (document_id is null or document_chunks.document_id = document_id)
  order by embedding <=> query_embedding
  limit match_count;
$function$;
CREATE OR REPLACE FUNCTION public.set_updated_at()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
begin
  new.updated_at = now();
  return new;
end;
$function$;
grant delete on table "public"."allocation_models" to "anon";
grant insert on table "public"."allocation_models" to "anon";
grant references on table "public"."allocation_models" to "anon";
grant select on table "public"."allocation_models" to "anon";
grant trigger on table "public"."allocation_models" to "anon";
grant truncate on table "public"."allocation_models" to "anon";
grant update on table "public"."allocation_models" to "anon";
grant delete on table "public"."allocation_models" to "authenticated";
grant insert on table "public"."allocation_models" to "authenticated";
grant references on table "public"."allocation_models" to "authenticated";
grant select on table "public"."allocation_models" to "authenticated";
grant trigger on table "public"."allocation_models" to "authenticated";
grant truncate on table "public"."allocation_models" to "authenticated";
grant update on table "public"."allocation_models" to "authenticated";
grant delete on table "public"."allocation_models" to "service_role";
grant insert on table "public"."allocation_models" to "service_role";
grant references on table "public"."allocation_models" to "service_role";
grant select on table "public"."allocation_models" to "service_role";
grant trigger on table "public"."allocation_models" to "service_role";
grant truncate on table "public"."allocation_models" to "service_role";
grant update on table "public"."allocation_models" to "service_role";
grant delete on table "public"."chats" to "anon";
grant insert on table "public"."chats" to "anon";
grant references on table "public"."chats" to "anon";
grant select on table "public"."chats" to "anon";
grant trigger on table "public"."chats" to "anon";
grant truncate on table "public"."chats" to "anon";
grant update on table "public"."chats" to "anon";
grant delete on table "public"."chats" to "authenticated";
grant insert on table "public"."chats" to "authenticated";
grant references on table "public"."chats" to "authenticated";
grant select on table "public"."chats" to "authenticated";
grant trigger on table "public"."chats" to "authenticated";
grant truncate on table "public"."chats" to "authenticated";
grant update on table "public"."chats" to "authenticated";
grant delete on table "public"."chats" to "service_role";
grant insert on table "public"."chats" to "service_role";
grant references on table "public"."chats" to "service_role";
grant select on table "public"."chats" to "service_role";
grant trigger on table "public"."chats" to "service_role";
grant truncate on table "public"."chats" to "service_role";
grant update on table "public"."chats" to "service_role";
grant delete on table "public"."document_chunks" to "anon";
grant insert on table "public"."document_chunks" to "anon";
grant references on table "public"."document_chunks" to "anon";
grant select on table "public"."document_chunks" to "anon";
grant trigger on table "public"."document_chunks" to "anon";
grant truncate on table "public"."document_chunks" to "anon";
grant update on table "public"."document_chunks" to "anon";
grant delete on table "public"."document_chunks" to "authenticated";
grant insert on table "public"."document_chunks" to "authenticated";
grant references on table "public"."document_chunks" to "authenticated";
grant select on table "public"."document_chunks" to "authenticated";
grant trigger on table "public"."document_chunks" to "authenticated";
grant truncate on table "public"."document_chunks" to "authenticated";
grant update on table "public"."document_chunks" to "authenticated";
grant delete on table "public"."document_chunks" to "service_role";
grant insert on table "public"."document_chunks" to "service_role";
grant references on table "public"."document_chunks" to "service_role";
grant select on table "public"."document_chunks" to "service_role";
grant trigger on table "public"."document_chunks" to "service_role";
grant truncate on table "public"."document_chunks" to "service_role";
grant update on table "public"."document_chunks" to "service_role";
grant delete on table "public"."documents" to "anon";
grant insert on table "public"."documents" to "anon";
grant references on table "public"."documents" to "anon";
grant select on table "public"."documents" to "anon";
grant trigger on table "public"."documents" to "anon";
grant truncate on table "public"."documents" to "anon";
grant update on table "public"."documents" to "anon";
grant delete on table "public"."documents" to "authenticated";
grant insert on table "public"."documents" to "authenticated";
grant references on table "public"."documents" to "authenticated";
grant select on table "public"."documents" to "authenticated";
grant trigger on table "public"."documents" to "authenticated";
grant truncate on table "public"."documents" to "authenticated";
grant update on table "public"."documents" to "authenticated";
grant delete on table "public"."documents" to "service_role";
grant insert on table "public"."documents" to "service_role";
grant references on table "public"."documents" to "service_role";
grant select on table "public"."documents" to "service_role";
grant trigger on table "public"."documents" to "service_role";
grant truncate on table "public"."documents" to "service_role";
grant update on table "public"."documents" to "service_role";
grant delete on table "public"."files" to "anon";
grant insert on table "public"."files" to "anon";
grant references on table "public"."files" to "anon";
grant select on table "public"."files" to "anon";
grant trigger on table "public"."files" to "anon";
grant truncate on table "public"."files" to "anon";
grant update on table "public"."files" to "anon";
grant delete on table "public"."files" to "authenticated";
grant insert on table "public"."files" to "authenticated";
grant references on table "public"."files" to "authenticated";
grant select on table "public"."files" to "authenticated";
grant trigger on table "public"."files" to "authenticated";
grant truncate on table "public"."files" to "authenticated";
grant update on table "public"."files" to "authenticated";
grant delete on table "public"."files" to "service_role";
grant insert on table "public"."files" to "service_role";
grant references on table "public"."files" to "service_role";
grant select on table "public"."files" to "service_role";
grant trigger on table "public"."files" to "service_role";
grant truncate on table "public"."files" to "service_role";
grant update on table "public"."files" to "service_role";
grant delete on table "public"."market_indicators" to "anon";
grant insert on table "public"."market_indicators" to "anon";
grant references on table "public"."market_indicators" to "anon";
grant select on table "public"."market_indicators" to "anon";
grant trigger on table "public"."market_indicators" to "anon";
grant truncate on table "public"."market_indicators" to "anon";
grant update on table "public"."market_indicators" to "anon";
grant delete on table "public"."market_indicators" to "authenticated";
grant insert on table "public"."market_indicators" to "authenticated";
grant references on table "public"."market_indicators" to "authenticated";
grant select on table "public"."market_indicators" to "authenticated";
grant trigger on table "public"."market_indicators" to "authenticated";
grant truncate on table "public"."market_indicators" to "authenticated";
grant update on table "public"."market_indicators" to "authenticated";
grant delete on table "public"."market_indicators" to "service_role";
grant insert on table "public"."market_indicators" to "service_role";
grant references on table "public"."market_indicators" to "service_role";
grant select on table "public"."market_indicators" to "service_role";
grant trigger on table "public"."market_indicators" to "service_role";
grant truncate on table "public"."market_indicators" to "service_role";
grant update on table "public"."market_indicators" to "service_role";
grant delete on table "public"."message_chunks" to "anon";
grant insert on table "public"."message_chunks" to "anon";
grant references on table "public"."message_chunks" to "anon";
grant select on table "public"."message_chunks" to "anon";
grant trigger on table "public"."message_chunks" to "anon";
grant truncate on table "public"."message_chunks" to "anon";
grant update on table "public"."message_chunks" to "anon";
grant delete on table "public"."message_chunks" to "authenticated";
grant insert on table "public"."message_chunks" to "authenticated";
grant references on table "public"."message_chunks" to "authenticated";
grant select on table "public"."message_chunks" to "authenticated";
grant trigger on table "public"."message_chunks" to "authenticated";
grant truncate on table "public"."message_chunks" to "authenticated";
grant update on table "public"."message_chunks" to "authenticated";
grant delete on table "public"."message_chunks" to "service_role";
grant insert on table "public"."message_chunks" to "service_role";
grant references on table "public"."message_chunks" to "service_role";
grant select on table "public"."message_chunks" to "service_role";
grant trigger on table "public"."message_chunks" to "service_role";
grant truncate on table "public"."message_chunks" to "service_role";
grant update on table "public"."message_chunks" to "service_role";
grant delete on table "public"."messages" to "anon";
grant insert on table "public"."messages" to "anon";
grant references on table "public"."messages" to "anon";
grant select on table "public"."messages" to "anon";
grant trigger on table "public"."messages" to "anon";
grant truncate on table "public"."messages" to "anon";
grant update on table "public"."messages" to "anon";
grant delete on table "public"."messages" to "authenticated";
grant insert on table "public"."messages" to "authenticated";
grant references on table "public"."messages" to "authenticated";
grant select on table "public"."messages" to "authenticated";
grant trigger on table "public"."messages" to "authenticated";
grant truncate on table "public"."messages" to "authenticated";
grant update on table "public"."messages" to "authenticated";
grant delete on table "public"."messages" to "service_role";
grant insert on table "public"."messages" to "service_role";
grant references on table "public"."messages" to "service_role";
grant select on table "public"."messages" to "service_role";
grant trigger on table "public"."messages" to "service_role";
grant truncate on table "public"."messages" to "service_role";
grant update on table "public"."messages" to "service_role";
grant delete on table "public"."user_allocations" to "anon";
grant insert on table "public"."user_allocations" to "anon";
grant references on table "public"."user_allocations" to "anon";
grant select on table "public"."user_allocations" to "anon";
grant trigger on table "public"."user_allocations" to "anon";
grant truncate on table "public"."user_allocations" to "anon";
grant update on table "public"."user_allocations" to "anon";
grant delete on table "public"."user_allocations" to "authenticated";
grant insert on table "public"."user_allocations" to "authenticated";
grant references on table "public"."user_allocations" to "authenticated";
grant select on table "public"."user_allocations" to "authenticated";
grant trigger on table "public"."user_allocations" to "authenticated";
grant truncate on table "public"."user_allocations" to "authenticated";
grant update on table "public"."user_allocations" to "authenticated";
grant delete on table "public"."user_allocations" to "service_role";
grant insert on table "public"."user_allocations" to "service_role";
grant references on table "public"."user_allocations" to "service_role";
grant select on table "public"."user_allocations" to "service_role";
grant trigger on table "public"."user_allocations" to "service_role";
grant truncate on table "public"."user_allocations" to "service_role";
grant update on table "public"."user_allocations" to "service_role";
create policy "chats_delete_own"
  on "public"."chats"
  as permissive
  for delete
  to public
using ((user_id = auth.uid()));
create policy "chats_insert_own"
  on "public"."chats"
  as permissive
  for insert
  to public
with check ((user_id = auth.uid()));
create policy "chats_select_own"
  on "public"."chats"
  as permissive
  for select
  to public
using ((user_id = auth.uid()));
create policy "chats_update_own"
  on "public"."chats"
  as permissive
  for update
  to public
using ((user_id = auth.uid()));
create policy "documents_delete_own"
  on "public"."documents"
  as permissive
  for delete
  to public
using ((user_id = auth.uid()));
create policy "documents_insert_own"
  on "public"."documents"
  as permissive
  for insert
  to public
with check ((user_id = auth.uid()));
create policy "documents_select_via_files"
  on "public"."documents"
  as permissive
  for select
  to public
using ((user_id = auth.uid()));
create policy "documents_update_own"
  on "public"."documents"
  as permissive
  for update
  to public
using ((user_id = auth.uid()));
create policy "files_delete_own"
  on "public"."files"
  as permissive
  for delete
  to public
using ((user_id = auth.uid()));
create policy "files_insert_own"
  on "public"."files"
  as permissive
  for insert
  to public
with check ((user_id = auth.uid()));
create policy "files_select_own"
  on "public"."files"
  as permissive
  for select
  to public
using ((user_id = auth.uid()));
create policy "files_update_own"
  on "public"."files"
  as permissive
  for select
  to public
using ((user_id = auth.uid()));
create policy "allow authenticated select 84ce0l_0"
  on "storage"."objects"
  as permissive
  for select
  to authenticated
using ((bucket_id = 'user-files'::text));
create policy "allow authenticated upload 84ce0l_0"
  on "storage"."objects"
  as permissive
  for insert
  to authenticated
with check ((bucket_id = 'user-files'::text));
