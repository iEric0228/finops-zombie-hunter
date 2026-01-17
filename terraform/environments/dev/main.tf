terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  region = "us-east-1"
}

module "IAM" {
  source = "../../modules/IAM"
}

module "sns" {
  source             = "../../modules/sns"
  notification_email = "ericchiu0228@gmail.com"
}

module "lambda" {
  source        = "../../modules/lambda"
  function_name = "FinOps-Zombie-Hunter"
  i_am_role_arn = module.IAM.lambda_exec_role_arn
  sns_topic_arn = module.sns.topic_arn
  env_vars = {
    "ENV"           = "dev"
    "SNS_TOPIC_ARN" = module.sns.topic_arn
  }
  common_tags = {
    "Environment" = "dev"
    "Project"     = "FinOps-Zombie-Hunter"
  }
}

module "event" {
  source               = "../../modules/event"
  rule_name            = "FinOps-Zombie-Hunter-Schedule-Dev"
  schedule_expression  = "cron(0 0 ? * SUN *)"
  lambda_function_arn  = module.lambda.lambda_function_arn
  lambda_function_name = module.lambda.lambda_function_name
  common_tags = {
    "Environment" = "dev"
    "Project"     = "FinOps-Zombie-Hunter"
  }
}
