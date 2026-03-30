terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Environment = var.environment
      Project     = "FinOps-Zombie-Hunter"
      ManagedBy   = "Terraform"
    }
  }
}

module "iam" {
  source = "../../modules/IAM"

  function_name = "FinOps-Zombie-Hunter-${var.environment}"
  sns_topic_arn = module.sns.topic_arn
}

module "sns" {
  source             = "../../modules/sns"
  notification_email = var.notification_email
}

module "lambda" {
  source        = "../../modules/lambda"
  function_name = "FinOps-Zombie-Hunter-${var.environment}"
  iam_role_arn  = module.iam.lambda_exec_role_arn
  sns_topic_arn = module.sns.topic_arn
  timeout       = var.lambda_timeout
  memory_size   = var.lambda_memory_size
  env_vars = {
    "ENV"           = var.environment
    "DRY_RUN"       = tostring(var.dry_run)
    "SNS_TOPIC_ARN" = module.sns.topic_arn
  }
}

module "event" {
  source               = "../../modules/event"
  rule_name            = "FinOps-Zombie-Hunter-Schedule-${var.environment}"
  schedule_expression  = var.schedule_expression
  lambda_function_arn  = module.lambda.lambda_function_arn
  lambda_function_name = module.lambda.lambda_function_name
}
