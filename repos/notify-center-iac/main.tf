# ============================================================
# notify-center IaC — 通知中心基礎設施定義
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
  service_name = "notify-center"
  region       = "asia-east1"
  project_id   = "esun-fintech-prod"

  notification_dataset = "engagement_ops"
  audit_table_name     = "notification_delivery_audit"
}

resource "google_cloud_run_v2_service" "notify_center" {
  name     = local.service_name
  location = local.region
  project  = local.project_id

  template {
    containers {
      image = "asia-east1-docker.pkg.dev/${local.project_id}/app-images/notify-center:latest"

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }

      env {
        name  = "DEFAULT_LANGUAGE"
        value = "zh-TW"
      }
      env {
        name  = "NOTIFY_BATCH_SIZE"
        value = "200"
      }
      env {
        name  = "AUDIT_DATASET_ID"
        value = local.notification_dataset
      }
      env {
        name  = "AUDIT_TABLE_NAME"
        value = local.audit_table_name
      }
      env {
        name  = "SERVICE_ENV"
        value = "production"
      }
    }

    scaling {
      min_instance_count = 1
      max_instance_count = 5
    }
  }
}

resource "google_bigquery_table" "notification_delivery_audit" {
  dataset_id = local.notification_dataset
  table_id   = local.audit_table_name
  project    = local.project_id

  schema = jsonencode([
    { name = "message_id",   type = "STRING",    mode = "REQUIRED" },
    { name = "customer_id",  type = "STRING",    mode = "REQUIRED" },
    { name = "channel",      type = "STRING",    mode = "REQUIRED" },
    { name = "template_id",  type = "STRING",    mode = "REQUIRED" },
    { name = "delivered_at", type = "TIMESTAMP", mode = "REQUIRED" }
  ])
}

output "notify_center_url" {
  description = "notify-center Cloud Run 服務 URL"
  value       = google_cloud_run_v2_service.notify_center.uri
}