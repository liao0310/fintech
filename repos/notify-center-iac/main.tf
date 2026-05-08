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
  service_name      = "notify-center"
  region            = "asia-east1"
  project_id        = "esun-fintech-prod"

  cloudsql_instance = "notify-center-sql-instance"
  cloudsql_database = "notify_center_db"
  audit_table_name  = "notification_delivery_audit"
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
        name  = "CLOUDSQL_INSTANCE"
        value = local.cloudsql_instance
      }
      env {
        name  = "CLOUDSQL_DATABASE"
        value = local.cloudsql_database
      }
      env {
        name  = "AUDIT_TABLE_NAME"
        value = local.audit_table_name
      }
      env {
        name  = "SERVICE_ENV"
        value = "production"
      }

    scaling {
      min_instance_count = 1
      max_instance_count = 5
    }
  }
}

resource "google_sql_database_instance" "notify_center_instance" {
  name             = local.cloudsql_instance
  database_version = "POSTGRES_14"
  region           = local.region

  settings {
    tier = "db-f1-micro"
  }
}

resource "google_sql_database" "notify_center_db" {
  name     = local.cloudsql_database
  instance = google_sql_database_instance.notify_center_instance.name
}

resource "google_sql_user" "notify_center_user" {
  name     = "notify_user"
  instance = google_sql_database_instance.notify_center_instance.name
  password = var.db_password
}

output "notify_center_url" {
  description = "notify-center Cloud Run 服務 URL"
  value       = google_cloud_run_v2_service.notify_center.uri
}