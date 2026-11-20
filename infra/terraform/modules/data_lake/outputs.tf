output "bucket_name" {
  value = aws_s3_bucket.lake.bucket
}

output "bucket_arn" {
  value = aws_s3_bucket.lake.arn
}

output "glue_database" {
  value = aws_glue_catalog_database.this.name
}
