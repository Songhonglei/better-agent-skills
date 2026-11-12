CREATE TABLE "app_config" (
	"key" text PRIMARY KEY NOT NULL,
	"value" jsonb NOT NULL,
	"updated_by" text,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "collector_nonces" (
	"nonce" text PRIMARY KEY NOT NULL,
	"expires_at" timestamp with time zone NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "expense_issue_usage" (
	"issue_id" text PRIMARY KEY NOT NULL,
	"identifier" text NOT NULL,
	"title" text NOT NULL,
	"project_id" text,
	"project_name" text,
	"assignee_agent_id" text,
	"assignee_agent_name" text,
	"agent_attribution_source" text,
	"creator_type" text,
	"creator_id" text,
	"creator_name" text,
	"initiator_id" text,
	"initiator_name" text,
	"initiator_email" text,
	"initiator_precise" boolean,
	"initiator_source" text,
	"input_tokens" bigint DEFAULT 0 NOT NULL,
	"output_tokens" bigint DEFAULT 0 NOT NULL,
	"cache_read_tokens" bigint DEFAULT 0 NOT NULL,
	"cache_write_tokens" bigint DEFAULT 0 NOT NULL,
	"uncosted_input_tokens" bigint DEFAULT 0 NOT NULL,
	"uncosted_output_tokens" bigint DEFAULT 0 NOT NULL,
	"uncosted_cache_read_tokens" bigint DEFAULT 0 NOT NULL,
	"uncosted_cache_write_tokens" bigint DEFAULT 0 NOT NULL,
	"cost_usd_ticks" bigint DEFAULT 0 NOT NULL,
	"model_usage" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"last_activity_at" timestamp with time zone NOT NULL,
	"collected_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "expense_model_prices" (
	"id" text PRIMARY KEY NOT NULL,
	"provider" text NOT NULL,
	"model" text NOT NULL,
	"canonical_key" text GENERATED ALWAYS AS ((
    regexp_replace(regexp_replace(regexp_replace(lower(translate("provider", '（）', '()')), '\((thinking|high|low)\)', '', 'g'), '[^a-z0-9.]+', '', 'g'), '(thinking|high|low)$', '')
    || '::' ||
    regexp_replace(regexp_replace(regexp_replace(lower(translate("model", '（）', '()')), '\((thinking|high|low)\)', '', 'g'), '[^a-z0-9.]+', '', 'g'), '(thinking|high|low)$', '')
  )) STORED,
	"display_name" text NOT NULL,
	"currency" text DEFAULT 'USD' NOT NULL,
	"usd_exchange_rate" double precision DEFAULT 1 NOT NULL,
	"input_per_million" double precision NOT NULL,
	"output_per_million" double precision NOT NULL,
	"cache_read_per_million" double precision NOT NULL,
	"cache_write_per_million" double precision NOT NULL,
	"effective_from" date NOT NULL,
	"effective_to" date,
	"updated_by" text,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "expense_runtime_usage" (
	"runtime_id" text NOT NULL,
	"runtime_name" text NOT NULL,
	"usage_date" date NOT NULL,
	"provider" text NOT NULL,
	"model" text NOT NULL,
	"input_tokens" bigint DEFAULT 0 NOT NULL,
	"output_tokens" bigint DEFAULT 0 NOT NULL,
	"cache_read_tokens" bigint DEFAULT 0 NOT NULL,
	"cache_write_tokens" bigint DEFAULT 0 NOT NULL,
	"collected_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "expense_runtime_usage_runtime_id_usage_date_provider_model_pk" PRIMARY KEY("runtime_id","usage_date","provider","model")
);
--> statement-breakpoint
CREATE TABLE "expense_task_usage" (
	"task_id" text NOT NULL,
	"usage_date" date NOT NULL,
	"agent_id" text NOT NULL,
	"agent_name" text NOT NULL,
	"runtime_id" text,
	"runtime_name" text,
	"provider" text NOT NULL,
	"model" text NOT NULL,
	"issue_id" text,
	"project_id" text,
	"project_name" text,
	"initiator" text,
	"delegation_path" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"input_tokens" bigint DEFAULT 0 NOT NULL,
	"output_tokens" bigint DEFAULT 0 NOT NULL,
	"cache_read_tokens" bigint DEFAULT 0 NOT NULL,
	"cache_write_tokens" bigint DEFAULT 0 NOT NULL,
	"collected_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "expense_task_usage_task_id_provider_model_pk" PRIMARY KEY("task_id","provider","model")
);
--> statement-breakpoint
CREATE INDEX "collector_nonces_expires_at_idx" ON "collector_nonces" USING btree ("expires_at");--> statement-breakpoint
CREATE INDEX "expense_issue_usage_activity_idx" ON "expense_issue_usage" USING btree ("last_activity_at");--> statement-breakpoint
CREATE INDEX "expense_issue_usage_agent_idx" ON "expense_issue_usage" USING btree ("assignee_agent_id");--> statement-breakpoint
CREATE INDEX "expense_issue_usage_project_idx" ON "expense_issue_usage" USING btree ("project_id");--> statement-breakpoint
CREATE INDEX "expense_issue_usage_creator_idx" ON "expense_issue_usage" USING btree ("creator_id");--> statement-breakpoint
CREATE UNIQUE INDEX "expense_model_prices_canonical_from_idx" ON "expense_model_prices" USING btree ("canonical_key","effective_from");--> statement-breakpoint
CREATE INDEX "expense_model_prices_lookup_idx" ON "expense_model_prices" USING btree ("provider","model","effective_from","effective_to");--> statement-breakpoint
CREATE INDEX "expense_runtime_usage_date_idx" ON "expense_runtime_usage" USING btree ("usage_date");--> statement-breakpoint
CREATE INDEX "expense_task_usage_date_idx" ON "expense_task_usage" USING btree ("usage_date");--> statement-breakpoint
CREATE INDEX "expense_task_usage_agent_idx" ON "expense_task_usage" USING btree ("agent_id");--> statement-breakpoint
CREATE INDEX "expense_task_usage_project_idx" ON "expense_task_usage" USING btree ("project_id");--> statement-breakpoint
CREATE INDEX "expense_task_usage_initiator_idx" ON "expense_task_usage" USING btree ("initiator");