terraform {
    backend "s3" {
        bucket         = "finops-zombie-hunter"
        key           = "dev/terraform.tfstate"
        region         = "us-east-1"
        dynamodb_table = "terraform-lock-finops"
        encrypt        = true
    }
}

provider "aws" {
    region = "us-east-1"
}



module "IAM" {
    source = "../../modules/IAM"
}

module "lambda" {
    source       = "../../modules/lambda"
    function_name     = "FinOps-Zombie-Hunter "
    source_file_path = "../../src/hunter.py"
    i_am_role_arn = aws_iam_role.lambda_exec.arn
    env_vars     = {
        "ENV" = "dev"
    }
    tags = {
        "Environment" = "dev"
        "Project"     = "FinOps-Zombie-Hunter"
    }
}

module "event" {
    source = "../../modules/event"
    rule_name = "FinOps-Zombie-Hunter-Schedule-Dev"
    schedule_expression = "cron(0 0 ? * SUN *)"
    lambda_function_arn = module.lambda.lambda.lambda_function_arn
    lambda_function_name = module.lambda.lambda.function_name
    common_tags = {
        "Environment" = "dev"
        "Project"     = "FinOps-Zombie-Hunter"
    }
}

