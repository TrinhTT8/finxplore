variable "bucket_name" {
  description = "Data lake bucket holding curated/ (table data) and athena-results/ (query output)"
  type        = string
}

variable "glue_database" {
  description = "Glue database the tables are created in"
  type        = string
}

variable "bytes_scanned_cutoff" {
  description = "Per-query scan limit in BYTES for every workgroup (AWS minimum is 10 MB)"
  type        = number
  default     = 104857600 # 100 MB -> worst case about $0.0005 per query at $5/TB
}
