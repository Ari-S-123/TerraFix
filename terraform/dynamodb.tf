resource "aws_dynamodb_table" "remediation_history" {
  name           = var.dynamodb_table_name
  billing_mode   = "PAY_PER_REQUEST"
  hash_key       = "event_id"
  range_key      = "timestamp"
  
  attribute {
    name = "event_id"
    type = "S"
  }
  
  attribute {
    name = "timestamp"
    type = "N"
  }
  
  tags = {
    Name = "self-healing-cloud"
  }
}

