output "app_workgroup" {
  value = aws_athena_workgroup.this["app"].name
}

output "ai_workgroup" {
  value = aws_athena_workgroup.this["ai"].name
}

output "table_names" {
  value = [
    aws_glue_catalog_table.facts.name,
    aws_glue_catalog_table.companies.name,
    aws_glue_catalog_table.sector_benchmarks.name,
  ]
}
