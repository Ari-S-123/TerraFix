terraform {
  required_version = ">= 1.0"
  
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

# Package Lambda function
data "archive_file" "lambda_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../backend/src"
  output_path = "${path.module}/../backend/lambda.zip"
}

# Package Lambda layer (dependencies)
resource "null_resource" "lambda_dependencies" {
  triggers = {
    requirements = filemd5("${path.module}/../backend/requirements.txt")
  }
  
  provisioner "local-exec" {
    command = <<EOF
      mkdir -p ${path.module}/../backend/layer/python
      pip install -r ${path.module}/../backend/requirements.txt -t ${path.module}/../backend/layer/python --upgrade
    EOF
  }
}

data "archive_file" "lambda_layer_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../backend/layer"
  output_path = "${path.module}/../backend/layer.zip"
  
  depends_on = [null_resource.lambda_dependencies]
}

resource "aws_lambda_layer_version" "dependencies" {
  filename            = data.archive_file.lambda_layer_zip.output_path
  layer_name          = "remediation-dependencies"
  compatible_runtimes = ["python3.12"]
  source_code_hash    = data.archive_file.lambda_layer_zip.output_base64sha256
}

