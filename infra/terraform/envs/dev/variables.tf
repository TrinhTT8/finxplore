variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "environment" {
  type    = string
  default = "dev"
}

variable "alert_email" {
  description = "Email address that receives budget and pipeline alerts"
  type        = string
}

variable "glue_database" {
  type    = string
  default = "finxplore"
}
