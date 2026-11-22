# Athena workgroups + Glue table definitions over the curated Parquet layer.
#   finxplore-app   used by the API Lambda (company pages, compare)
#   ai-readonly     used by the AI analyst; read-only is enforced by its IAM role (Phase 4)
# Both cap every query at var.bytes_scanned_cutoff and write results to athena-results/<name>/
# (expired after 7 days by the data_lake lifecycle rule).

locals {
  workgroups = {
    app = "finxplore-app"
    ai  = "ai-readonly"
  }

  parquet = {
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"
    serde         = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
  }
}

# ---------- Workgroups ----------

resource "aws_athena_workgroup" "this" {
  for_each = local.workgroups

  name          = each.value
  force_destroy = true # allow `terraform destroy` even if saved queries exist

  configuration {
    enforce_workgroup_configuration    = true # clients can't override the limits below
    publish_cloudwatch_metrics_enabled = true
    bytes_scanned_cutoff_per_query     = var.bytes_scanned_cutoff

    engine_version {
      selected_engine_version = "Athena engine version 3"
    }

    result_configuration {
      output_location = "s3://${var.bucket_name}/athena-results/${each.value}/"
      encryption_configuration {
        encryption_option = "SSE_S3"
      }
    }
  }
}

# ---------- Tables ----------

# One row per company, metric and reporting period. Partitioned by fiscal_year with
# partition projection, so no crawler or MSCK REPAIR is needed when new years arrive.
resource "aws_glue_catalog_table" "facts" {
  name          = "facts"
  database_name = var.glue_database
  table_type    = "EXTERNAL_TABLE" # Athena doesn't own the files; dropping the table keeps the data

  parameters = {
    EXTERNAL                       = "TRUE"
    classification                 = "parquet"
    "projection.enabled"           = "true"
    "projection.fiscal_year.type"  = "integer"
    "projection.fiscal_year.range" = "2000,2035"
  }

  storage_descriptor {
    location      = "s3://${var.bucket_name}/curated/facts/"
    input_format  = local.parquet.input_format
    output_format = local.parquet.output_format

    ser_de_info {
      serialization_library = local.parquet.serde
    }

    columns {
      name = "cik"
      type = "string"
    }
    columns {
      name = "ticker"
      type = "string"
    }
    columns {
      name = "metric"
      type = "string"
    }
    columns {
      name = "value"
      type = "double"
    }
    columns {
      name = "unit"
      type = "string"
    }
    columns {
      name = "fiscal_period"
      type = "string"
    }
    columns {
      name = "period_end"
      type = "string"
    }
    columns {
      name = "form"
      type = "string"
    }
    columns {
      name = "filed_date"
      type = "string"
    }
    columns {
      name = "accession_no"
      type = "string"
    }
  }

  # Comes from the folder name (fiscal_year=2023/), not from inside the Parquet files
  partition_keys {
    name = "fiscal_year"
    type = "int"
  }
}

resource "aws_glue_catalog_table" "companies" {
  name          = "companies"
  database_name = var.glue_database
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    EXTERNAL       = "TRUE"
    classification = "parquet"
  }

  storage_descriptor {
    location      = "s3://${var.bucket_name}/curated/companies/"
    input_format  = local.parquet.input_format
    output_format = local.parquet.output_format

    ser_de_info {
      serialization_library = local.parquet.serde
    }

    columns {
      name = "cik"
      type = "string"
    }
    columns {
      name = "ticker"
      type = "string"
    }
    columns {
      name = "name"
      type = "string"
    }
    columns {
      name = "sector"
      type = "string"
    }
    columns {
      name = "exchange"
      type = "string"
    }
  }
}

# Median of each metric per sector and fiscal year, recomputed nightly. Small table
# (~11 sectors x ~15 metrics x ~15 years), so no partitioning.
resource "aws_glue_catalog_table" "sector_benchmarks" {
  name          = "sector_benchmarks"
  database_name = var.glue_database
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    EXTERNAL       = "TRUE"
    classification = "parquet"
  }

  storage_descriptor {
    location      = "s3://${var.bucket_name}/curated/sector_benchmarks/"
    input_format  = local.parquet.input_format
    output_format = local.parquet.output_format

    ser_de_info {
      serialization_library = local.parquet.serde
    }

    columns {
      name = "sector"
      type = "string"
    }
    columns {
      name = "metric"
      type = "string"
    }
    columns {
      name = "fiscal_year"
      type = "int"
    }
    columns {
      name = "median_value"
      type = "double" # ratios are decimals; USD values exceed 32-bit int
    }
    columns {
      name = "company_count"
      type = "int"
    }
  }
}
