output "data_lake_bucket" {
  value = module.data_lake.bucket_name
}

output "glue_database" {
  value = module.data_lake.glue_database
}
