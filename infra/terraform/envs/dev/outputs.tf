output "data_lake_bucket" {
  value = module.data_lake.bucket_name
}

output "athena_workgroups" {
  value = [module.athena.app_workgroup, module.athena.ai_workgroup]
}

output "glue_database" {
  value = module.data_lake.glue_database
}
