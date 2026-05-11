# ============================================================
# vip-svc IaC — 高端客戶識別服務基礎設施定義
# ============================================================

terraform {
  required_version = ">= 1.5"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

locals {
  service_name = "vip-svc"
  region       = "asia-east1"
  project_id   = "esun-fintech-prod"

  # VIP 判斷門檻 (AUM 單位：新台幣)
  vip_threshold_aum = 5000000
  vip_tier_a_label  = "VIP_A"
  vip_tier_b_label  = "VIP_B"
}

# ── Cloud Run 服務定義 ──────────────────────────────────────
resource "google_cloud_run_v2_service" "vip_svc" {
  name     = local.service_name
  location = local.region
  project  = local.project_id

  template {
    containers {
      image = "asia-east1-docker.pkg.dev/${local.project_id}/app-images/vip-svc:latest"

      resources {
        limits = {
          cpu    = "2"
          memory = "1Gi"
        }
      }

      # 環境變數設定
      env {
        name  = "VIP_THRESHOLD_AUM"
        value = tostring(local.vip_threshold_aum)
      }
      env {
        name  = "VIP_TIER_A_LABEL"
        value = local.vip_tier_a_label
      }
      env {
        name  = "VIP_TIER_B_LABEL"
        value = local.vip_tier_b_label
      }
      env {
        name  = "BQ_DATASET"
        value = "customer_analytics"
      }
      env {
        name  = "BQ_TABLE_VIP_RESULT"
        value = "vip_classification_result"
      }
      env {
        name  = "BQ_TABLE_AUM_SNAPSHOT"
        value = "aum_daily_snapshot"
      }
      env {
        name  = "SERVICE_ENV"
        value = "production"
      }
    }

    scaling {
      min_instance_count = 1
      max_instance_count = 10
    }
  }
}

# ── BigQuery Table：VIP 分類結果 ─────────────────────────────
resource "google_bigquery_table" "vip_classification_result" {
  dataset_id = "customer_analytics"
  table_id   = "vip_classification_result"
  project    = local.project_id

  schema = jsonencode([
    { name = "customer_id",   type = "STRING",    mode = "REQUIRED" },
    { name = "aum_value",     type = "FLOAT64",   mode = "REQUIRED" },
    { name = "vip_status",    type = "STRING",    mode = "REQUIRED" },
    { name = "classified_at", type = "TIMESTAMP", mode = "REQUIRED" }
  ])
}

# ── BigQuery Table：AUM 每日快照 ──────────────────────────────
resource "google_bigquery_table" "aum_daily_snapshot" {
  dataset_id = "customer_analytics"
  table_id   = "aum_daily_snapshot"
  project    = local.project_id

  schema = jsonencode([
    { name = "customer_id",  type = "STRING",  mode = "REQUIRED" },
    { name = "aum_value",    type = "FLOAT64", mode = "REQUIRED" },
    { name = "snapshot_date", type = "DATE",   mode = "REQUIRED" }
  ])
}

# ── IAM：允許 Cloud Run 存取 BigQuery ─────────────────────────
resource "google_project_iam_member" "vip_svc_bq_writer" {
  project = local.project_id
  role    = "roles/bigquery.dataEditor"
  member  = "serviceAccount:${google_cloud_run_v2_service.vip_svc.template[0].service_account}"
}

# ── 輸出值供其他模組參考 ─────────────────────────────────────
output "vip_svc_url" {
  description = "vip-svc Cloud Run 服務 URL（供下游 loan-api 呼叫）"
  value       = google_cloud_run_v2_service.vip_svc.uri
}

output "vip_threshold_aum" {
  description = "VIP 判斷門檻值"
  value       = local.vip_threshold_aum
}
