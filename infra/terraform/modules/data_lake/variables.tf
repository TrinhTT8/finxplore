variable "bucket_name" {
  type = string
}

variable "glue_database" {
  type = string
}

variable "raw_retention_days" {
  type    = number
  default = 30
}
