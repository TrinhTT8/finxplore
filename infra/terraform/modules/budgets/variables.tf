variable "name_prefix" {
  type = string
}

variable "alert_email" {
  type = string
}

variable "thresholds" {
  description = "Absolute USD amounts that trigger an email when actual spend exceeds them"
  type        = list(number)
  default     = [1, 5, 10]
}
