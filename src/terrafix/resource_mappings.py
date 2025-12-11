"""
AWS CloudFormation to Terraform resource type mappings.

This module provides a comprehensive mapping table for converting AWS
CloudFormation resource types to Terraform resource types. The naive
string manipulation approach fails for many resources where naming
conventions differ significantly.

Examples of resources with non-obvious mappings:
    - AWS::ElasticLoadBalancingV2::LoadBalancer -> aws_lb (not aws_elasticloadbalancingv2_loadbalancer)
    - AWS::Serverless::Function -> aws_lambda_function (not aws_serverless_function)
    - AWS::Logs::LogGroup -> aws_cloudwatch_log_group (not aws_logs_loggroup)

Usage:
    from terrafix.resource_mappings import aws_to_terraform_type

    tf_type = aws_to_terraform_type("AWS::S3::Bucket")
    # Returns: "aws_s3_bucket"

    tf_type = aws_to_terraform_type("AWS::ElasticLoadBalancingV2::LoadBalancer")
    # Returns: "aws_lb"
"""

from terrafix.logging_config import get_logger, log_with_context

logger = get_logger(__name__)


# Comprehensive mapping of AWS CloudFormation types to Terraform types
# Organized by service for maintainability
AWS_TO_TERRAFORM_TYPE_MAP: dict[str, str] = {
    # ==========================================================================
    # Compute Services
    # ==========================================================================
    "AWS::EC2::Instance": "aws_instance",
    "AWS::EC2::LaunchTemplate": "aws_launch_template",
    "AWS::EC2::SpotFleet": "aws_spot_fleet_request",
    "AWS::EC2::CapacityReservation": "aws_ec2_capacity_reservation",
    "AWS::EC2::Fleet": "aws_ec2_fleet",
    "AWS::EC2::Host": "aws_ec2_host",
    "AWS::EC2::PlacementGroup": "aws_placement_group",
    "AWS::EC2::KeyPair": "aws_key_pair",
    # Auto Scaling
    "AWS::AutoScaling::AutoScalingGroup": "aws_autoscaling_group",
    "AWS::AutoScaling::LaunchConfiguration": "aws_launch_configuration",
    "AWS::AutoScaling::LifecycleHook": "aws_autoscaling_lifecycle_hook",
    "AWS::AutoScaling::ScalingPolicy": "aws_autoscaling_policy",
    "AWS::AutoScaling::ScheduledAction": "aws_autoscaling_schedule",
    # Lambda
    "AWS::Lambda::Function": "aws_lambda_function",
    "AWS::Lambda::Alias": "aws_lambda_alias",
    "AWS::Lambda::EventSourceMapping": "aws_lambda_event_source_mapping",
    "AWS::Lambda::LayerVersion": "aws_lambda_layer_version",
    "AWS::Lambda::Permission": "aws_lambda_permission",
    "AWS::Lambda::Version": "aws_lambda_function",  # Versions are part of function
    "AWS::Lambda::Url": "aws_lambda_function_url",
    "AWS::Serverless::Function": "aws_lambda_function",  # SAM resource
    # ECS
    "AWS::ECS::Cluster": "aws_ecs_cluster",
    "AWS::ECS::Service": "aws_ecs_service",
    "AWS::ECS::TaskDefinition": "aws_ecs_task_definition",
    "AWS::ECS::TaskSet": "aws_ecs_task_set",
    "AWS::ECS::CapacityProvider": "aws_ecs_capacity_provider",
    "AWS::ECS::ClusterCapacityProviderAssociations": "aws_ecs_cluster_capacity_providers",
    # EKS
    "AWS::EKS::Cluster": "aws_eks_cluster",
    "AWS::EKS::Nodegroup": "aws_eks_node_group",
    "AWS::EKS::FargateProfile": "aws_eks_fargate_profile",
    "AWS::EKS::Addon": "aws_eks_addon",
    "AWS::EKS::IdentityProviderConfig": "aws_eks_identity_provider_config",
    # Batch
    "AWS::Batch::ComputeEnvironment": "aws_batch_compute_environment",
    "AWS::Batch::JobQueue": "aws_batch_job_queue",
    "AWS::Batch::JobDefinition": "aws_batch_job_definition",
    "AWS::Batch::SchedulingPolicy": "aws_batch_scheduling_policy",
    # ==========================================================================
    # Storage Services
    # ==========================================================================
    "AWS::S3::Bucket": "aws_s3_bucket",
    "AWS::S3::BucketPolicy": "aws_s3_bucket_policy",
    "AWS::S3::AccessPoint": "aws_s3_access_point",
    "AWS::S3::StorageLens": "aws_s3control_storage_lens_configuration",
    "AWS::S3Outposts::Bucket": "aws_s3outposts_bucket",
    # EFS
    "AWS::EFS::FileSystem": "aws_efs_file_system",
    "AWS::EFS::MountTarget": "aws_efs_mount_target",
    "AWS::EFS::AccessPoint": "aws_efs_access_point",
    # FSx
    "AWS::FSx::FileSystem": "aws_fsx_lustre_file_system",  # or other FSx types
    "AWS::FSx::Volume": "aws_fsx_openzfs_volume",
    # EBS
    "AWS::EC2::Volume": "aws_ebs_volume",
    "AWS::EC2::VolumeAttachment": "aws_volume_attachment",
    # Backup
    "AWS::Backup::BackupPlan": "aws_backup_plan",
    "AWS::Backup::BackupVault": "aws_backup_vault",
    "AWS::Backup::BackupSelection": "aws_backup_selection",
    # ==========================================================================
    # Database Services
    # ==========================================================================
    "AWS::RDS::DBInstance": "aws_db_instance",
    "AWS::RDS::DBCluster": "aws_rds_cluster",
    "AWS::RDS::DBSubnetGroup": "aws_db_subnet_group",
    "AWS::RDS::DBParameterGroup": "aws_db_parameter_group",
    "AWS::RDS::DBClusterParameterGroup": "aws_rds_cluster_parameter_group",
    "AWS::RDS::OptionGroup": "aws_db_option_group",
    "AWS::RDS::DBProxy": "aws_db_proxy",
    "AWS::RDS::DBProxyTargetGroup": "aws_db_proxy_default_target_group",
    "AWS::RDS::GlobalCluster": "aws_rds_global_cluster",
    "AWS::RDS::EventSubscription": "aws_db_event_subscription",
    # DynamoDB
    "AWS::DynamoDB::Table": "aws_dynamodb_table",
    "AWS::DynamoDB::GlobalTable": "aws_dynamodb_global_table",
    # ElastiCache
    "AWS::ElastiCache::CacheCluster": "aws_elasticache_cluster",
    "AWS::ElastiCache::ReplicationGroup": "aws_elasticache_replication_group",
    "AWS::ElastiCache::SubnetGroup": "aws_elasticache_subnet_group",
    "AWS::ElastiCache::ParameterGroup": "aws_elasticache_parameter_group",
    "AWS::ElastiCache::SecurityGroup": "aws_elasticache_security_group",
    "AWS::ElastiCache::User": "aws_elasticache_user",
    "AWS::ElastiCache::UserGroup": "aws_elasticache_user_group",
    # Redshift
    "AWS::Redshift::Cluster": "aws_redshift_cluster",
    "AWS::Redshift::ClusterSubnetGroup": "aws_redshift_subnet_group",
    "AWS::Redshift::ClusterParameterGroup": "aws_redshift_parameter_group",
    "AWS::Redshift::ClusterSecurityGroup": "aws_redshift_security_group",
    "AWS::Redshift::EventSubscription": "aws_redshift_event_subscription",
    "AWS::Redshift::ScheduledAction": "aws_redshift_scheduled_action",
    # DocumentDB
    "AWS::DocDB::DBCluster": "aws_docdb_cluster",
    "AWS::DocDB::DBInstance": "aws_docdb_cluster_instance",
    "AWS::DocDB::DBSubnetGroup": "aws_docdb_subnet_group",
    "AWS::DocDB::DBClusterParameterGroup": "aws_docdb_cluster_parameter_group",
    # Neptune
    "AWS::Neptune::DBCluster": "aws_neptune_cluster",
    "AWS::Neptune::DBInstance": "aws_neptune_cluster_instance",
    "AWS::Neptune::DBSubnetGroup": "aws_neptune_subnet_group",
    "AWS::Neptune::DBClusterParameterGroup": "aws_neptune_cluster_parameter_group",
    "AWS::Neptune::DBParameterGroup": "aws_neptune_parameter_group",
    # MemoryDB
    "AWS::MemoryDB::Cluster": "aws_memorydb_cluster",
    "AWS::MemoryDB::SubnetGroup": "aws_memorydb_subnet_group",
    "AWS::MemoryDB::ParameterGroup": "aws_memorydb_parameter_group",
    "AWS::MemoryDB::User": "aws_memorydb_user",
    "AWS::MemoryDB::ACL": "aws_memorydb_acl",
    # Timestream
    "AWS::Timestream::Database": "aws_timestreamwrite_database",
    "AWS::Timestream::Table": "aws_timestreamwrite_table",
    # ==========================================================================
    # Networking Services
    # ==========================================================================
    "AWS::EC2::VPC": "aws_vpc",
    "AWS::EC2::Subnet": "aws_subnet",
    "AWS::EC2::RouteTable": "aws_route_table",
    "AWS::EC2::Route": "aws_route",
    "AWS::EC2::InternetGateway": "aws_internet_gateway",
    "AWS::EC2::VPCGatewayAttachment": "aws_internet_gateway_attachment",
    "AWS::EC2::NatGateway": "aws_nat_gateway",
    "AWS::EC2::EIP": "aws_eip",
    "AWS::EC2::EIPAssociation": "aws_eip_association",
    "AWS::EC2::SecurityGroup": "aws_security_group",
    "AWS::EC2::SecurityGroupIngress": "aws_security_group_rule",
    "AWS::EC2::SecurityGroupEgress": "aws_security_group_rule",
    "AWS::EC2::NetworkAcl": "aws_network_acl",
    "AWS::EC2::NetworkAclEntry": "aws_network_acl_rule",
    "AWS::EC2::SubnetNetworkAclAssociation": "aws_network_acl_association",
    "AWS::EC2::SubnetRouteTableAssociation": "aws_route_table_association",
    "AWS::EC2::VPCEndpoint": "aws_vpc_endpoint",
    "AWS::EC2::VPCEndpointService": "aws_vpc_endpoint_service",
    "AWS::EC2::VPNGateway": "aws_vpn_gateway",
    "AWS::EC2::VPNConnection": "aws_vpn_connection",
    "AWS::EC2::CustomerGateway": "aws_customer_gateway",
    "AWS::EC2::TransitGateway": "aws_ec2_transit_gateway",
    "AWS::EC2::TransitGatewayAttachment": "aws_ec2_transit_gateway_vpc_attachment",
    "AWS::EC2::TransitGatewayRouteTable": "aws_ec2_transit_gateway_route_table",
    "AWS::EC2::VPCPeeringConnection": "aws_vpc_peering_connection",
    "AWS::EC2::NetworkInterface": "aws_network_interface",
    "AWS::EC2::NetworkInterfaceAttachment": "aws_network_interface_attachment",
    "AWS::EC2::FlowLog": "aws_flow_log",
    "AWS::EC2::DHCPOptions": "aws_vpc_dhcp_options",
    "AWS::EC2::VPCDHCPOptionsAssociation": "aws_vpc_dhcp_options_association",
    # ==========================================================================
    # Load Balancing
    # ==========================================================================
    # Classic ELB
    "AWS::ElasticLoadBalancing::LoadBalancer": "aws_elb",
    # ALB/NLB (v2)
    "AWS::ElasticLoadBalancingV2::LoadBalancer": "aws_lb",
    "AWS::ElasticLoadBalancingV2::TargetGroup": "aws_lb_target_group",
    "AWS::ElasticLoadBalancingV2::Listener": "aws_lb_listener",
    "AWS::ElasticLoadBalancingV2::ListenerRule": "aws_lb_listener_rule",
    "AWS::ElasticLoadBalancingV2::ListenerCertificate": "aws_lb_listener_certificate",
    # ==========================================================================
    # IAM & Security
    # ==========================================================================
    "AWS::IAM::Role": "aws_iam_role",
    "AWS::IAM::Policy": "aws_iam_policy",
    "AWS::IAM::User": "aws_iam_user",
    "AWS::IAM::Group": "aws_iam_group",
    "AWS::IAM::InstanceProfile": "aws_iam_instance_profile",
    "AWS::IAM::ManagedPolicy": "aws_iam_policy",
    "AWS::IAM::ServiceLinkedRole": "aws_iam_service_linked_role",
    "AWS::IAM::AccessKey": "aws_iam_access_key",
    "AWS::IAM::UserToGroupAddition": "aws_iam_user_group_membership",
    "AWS::IAM::OIDCProvider": "aws_iam_openid_connect_provider",
    "AWS::IAM::SAMLProvider": "aws_iam_saml_provider",
    # KMS
    "AWS::KMS::Key": "aws_kms_key",
    "AWS::KMS::Alias": "aws_kms_alias",
    "AWS::KMS::ReplicaKey": "aws_kms_replica_key",
    # Secrets Manager
    "AWS::SecretsManager::Secret": "aws_secretsmanager_secret",
    "AWS::SecretsManager::SecretTargetAttachment": "aws_secretsmanager_secret_version",
    "AWS::SecretsManager::RotationSchedule": "aws_secretsmanager_secret_rotation",
    "AWS::SecretsManager::ResourcePolicy": "aws_secretsmanager_secret_policy",
    # SSM Parameter Store
    "AWS::SSM::Parameter": "aws_ssm_parameter",
    "AWS::SSM::Document": "aws_ssm_document",
    "AWS::SSM::MaintenanceWindow": "aws_ssm_maintenance_window",
    "AWS::SSM::Association": "aws_ssm_association",
    "AWS::SSM::PatchBaseline": "aws_ssm_patch_baseline",
    # ACM
    "AWS::CertificateManager::Certificate": "aws_acm_certificate",
    # ==========================================================================
    # Monitoring & Logging
    # ==========================================================================
    "AWS::CloudWatch::Alarm": "aws_cloudwatch_metric_alarm",
    "AWS::CloudWatch::CompositeAlarm": "aws_cloudwatch_composite_alarm",
    "AWS::CloudWatch::Dashboard": "aws_cloudwatch_dashboard",
    "AWS::CloudWatch::AnomalyDetector": "aws_cloudwatch_metric_alarm",  # Part of alarm
    "AWS::CloudWatch::MetricStream": "aws_cloudwatch_metric_stream",
    # CloudWatch Logs
    "AWS::Logs::LogGroup": "aws_cloudwatch_log_group",
    "AWS::Logs::LogStream": "aws_cloudwatch_log_stream",
    "AWS::Logs::MetricFilter": "aws_cloudwatch_log_metric_filter",
    "AWS::Logs::SubscriptionFilter": "aws_cloudwatch_log_subscription_filter",
    "AWS::Logs::Destination": "aws_cloudwatch_log_destination",
    "AWS::Logs::ResourcePolicy": "aws_cloudwatch_log_resource_policy",
    # EventBridge (CloudWatch Events)
    "AWS::Events::Rule": "aws_cloudwatch_event_rule",
    "AWS::Events::EventBus": "aws_cloudwatch_event_bus",
    "AWS::Events::EventBusPolicy": "aws_cloudwatch_event_bus_policy",
    "AWS::Events::Archive": "aws_cloudwatch_event_archive",
    "AWS::Events::Connection": "aws_cloudwatch_event_connection",
    "AWS::Events::ApiDestination": "aws_cloudwatch_event_api_destination",
    # X-Ray
    "AWS::XRay::Group": "aws_xray_group",
    "AWS::XRay::SamplingRule": "aws_xray_sampling_rule",
    # ==========================================================================
    # Messaging Services
    # ==========================================================================
    "AWS::SNS::Topic": "aws_sns_topic",
    "AWS::SNS::TopicPolicy": "aws_sns_topic_policy",
    "AWS::SNS::Subscription": "aws_sns_topic_subscription",
    "AWS::SQS::Queue": "aws_sqs_queue",
    "AWS::SQS::QueuePolicy": "aws_sqs_queue_policy",
    "AWS::Kinesis::Stream": "aws_kinesis_stream",
    "AWS::Kinesis::StreamConsumer": "aws_kinesis_stream_consumer",
    "AWS::KinesisFirehose::DeliveryStream": "aws_kinesis_firehose_delivery_stream",
    "AWS::MSK::Cluster": "aws_msk_cluster",
    "AWS::MSK::Configuration": "aws_msk_configuration",
    # ==========================================================================
    # API Gateway
    # ==========================================================================
    # REST API (v1)
    "AWS::ApiGateway::RestApi": "aws_api_gateway_rest_api",
    "AWS::ApiGateway::Resource": "aws_api_gateway_resource",
    "AWS::ApiGateway::Method": "aws_api_gateway_method",
    "AWS::ApiGateway::MethodResponse": "aws_api_gateway_method_response",
    "AWS::ApiGateway::Integration": "aws_api_gateway_integration",
    "AWS::ApiGateway::IntegrationResponse": "aws_api_gateway_integration_response",
    "AWS::ApiGateway::Stage": "aws_api_gateway_stage",
    "AWS::ApiGateway::Deployment": "aws_api_gateway_deployment",
    "AWS::ApiGateway::Authorizer": "aws_api_gateway_authorizer",
    "AWS::ApiGateway::Model": "aws_api_gateway_model",
    "AWS::ApiGateway::DomainName": "aws_api_gateway_domain_name",
    "AWS::ApiGateway::BasePathMapping": "aws_api_gateway_base_path_mapping",
    "AWS::ApiGateway::UsagePlan": "aws_api_gateway_usage_plan",
    "AWS::ApiGateway::UsagePlanKey": "aws_api_gateway_usage_plan_key",
    "AWS::ApiGateway::ApiKey": "aws_api_gateway_api_key",
    "AWS::ApiGateway::VpcLink": "aws_api_gateway_vpc_link",
    # HTTP API (v2)
    "AWS::ApiGatewayV2::Api": "aws_apigatewayv2_api",
    "AWS::ApiGatewayV2::Stage": "aws_apigatewayv2_stage",
    "AWS::ApiGatewayV2::Route": "aws_apigatewayv2_route",
    "AWS::ApiGatewayV2::Integration": "aws_apigatewayv2_integration",
    "AWS::ApiGatewayV2::Authorizer": "aws_apigatewayv2_authorizer",
    "AWS::ApiGatewayV2::Deployment": "aws_apigatewayv2_deployment",
    "AWS::ApiGatewayV2::DomainName": "aws_apigatewayv2_domain_name",
    "AWS::ApiGatewayV2::VpcLink": "aws_apigatewayv2_vpc_link",
    # ==========================================================================
    # CDN & DNS
    # ==========================================================================
    "AWS::CloudFront::Distribution": "aws_cloudfront_distribution",
    "AWS::CloudFront::OriginAccessIdentity": "aws_cloudfront_origin_access_identity",
    "AWS::CloudFront::OriginAccessControl": "aws_cloudfront_origin_access_control",
    "AWS::CloudFront::CachePolicy": "aws_cloudfront_cache_policy",
    "AWS::CloudFront::OriginRequestPolicy": "aws_cloudfront_origin_request_policy",
    "AWS::CloudFront::ResponseHeadersPolicy": "aws_cloudfront_response_headers_policy",
    "AWS::CloudFront::Function": "aws_cloudfront_function",
    "AWS::CloudFront::RealtimeLogConfig": "aws_cloudfront_realtime_log_config",
    "AWS::Route53::HostedZone": "aws_route53_zone",
    "AWS::Route53::RecordSet": "aws_route53_record",
    "AWS::Route53::RecordSetGroup": "aws_route53_record",
    "AWS::Route53::HealthCheck": "aws_route53_health_check",
    "AWS::Route53Resolver::ResolverEndpoint": "aws_route53_resolver_endpoint",
    "AWS::Route53Resolver::ResolverRule": "aws_route53_resolver_rule",
    "AWS::ACM::Certificate": "aws_acm_certificate",
    "AWS::ACMPCA::CertificateAuthority": "aws_acmpca_certificate_authority",
    # ==========================================================================
    # Cognito
    # ==========================================================================
    "AWS::Cognito::UserPool": "aws_cognito_user_pool",
    "AWS::Cognito::UserPoolClient": "aws_cognito_user_pool_client",
    "AWS::Cognito::UserPoolDomain": "aws_cognito_user_pool_domain",
    "AWS::Cognito::UserPoolGroup": "aws_cognito_user_group",
    "AWS::Cognito::UserPoolIdentityProvider": "aws_cognito_identity_provider",
    "AWS::Cognito::UserPoolResourceServer": "aws_cognito_resource_server",
    "AWS::Cognito::UserPoolUser": "aws_cognito_user",
    "AWS::Cognito::UserPoolUserToGroupAttachment": "aws_cognito_user_in_group",
    "AWS::Cognito::IdentityPool": "aws_cognito_identity_pool",
    "AWS::Cognito::IdentityPoolRoleAttachment": "aws_cognito_identity_pool_roles_attachment",
    # ==========================================================================
    # Step Functions & Workflow
    # ==========================================================================
    "AWS::StepFunctions::StateMachine": "aws_sfn_state_machine",
    "AWS::StepFunctions::Activity": "aws_sfn_activity",
    "AWS::Scheduler::Schedule": "aws_scheduler_schedule",
    "AWS::Scheduler::ScheduleGroup": "aws_scheduler_schedule_group",
    # ==========================================================================
    # WAF & Security
    # ==========================================================================
    "AWS::WAFv2::WebACL": "aws_wafv2_web_acl",
    "AWS::WAFv2::WebACLAssociation": "aws_wafv2_web_acl_association",
    "AWS::WAFv2::RuleGroup": "aws_wafv2_rule_group",
    "AWS::WAFv2::IPSet": "aws_wafv2_ip_set",
    "AWS::WAFv2::RegexPatternSet": "aws_wafv2_regex_pattern_set",
    # Shield
    "AWS::Shield::Protection": "aws_shield_protection",
    "AWS::Shield::ProtectionGroup": "aws_shield_protection_group",
    # GuardDuty
    "AWS::GuardDuty::Detector": "aws_guardduty_detector",
    "AWS::GuardDuty::Filter": "aws_guardduty_filter",
    "AWS::GuardDuty::IPSet": "aws_guardduty_ipset",
    "AWS::GuardDuty::ThreatIntelSet": "aws_guardduty_threatintelset",
    "AWS::GuardDuty::Member": "aws_guardduty_member",
    # Security Hub
    "AWS::SecurityHub::Hub": "aws_securityhub_account",
    "AWS::SecurityHub::Standard": "aws_securityhub_standards_subscription",
    # Config
    "AWS::Config::ConfigRule": "aws_config_config_rule",
    "AWS::Config::ConfigurationRecorder": "aws_config_configuration_recorder",
    "AWS::Config::DeliveryChannel": "aws_config_delivery_channel",
    "AWS::Config::ConformancePack": "aws_config_conformance_pack",
    "AWS::Config::AggregationAuthorization": "aws_config_aggregate_authorization",
    "AWS::Config::ConfigurationAggregator": "aws_config_configuration_aggregator",
    # ==========================================================================
    # CloudFormation & Deployment
    # ==========================================================================
    "AWS::CloudFormation::Stack": "aws_cloudformation_stack",
    "AWS::CloudFormation::StackSet": "aws_cloudformation_stack_set",
    "AWS::CodeBuild::Project": "aws_codebuild_project",
    "AWS::CodeBuild::SourceCredential": "aws_codebuild_source_credential",
    "AWS::CodePipeline::Pipeline": "aws_codepipeline",
    "AWS::CodePipeline::Webhook": "aws_codepipeline_webhook",
    "AWS::CodeDeploy::Application": "aws_codedeploy_app",
    "AWS::CodeDeploy::DeploymentGroup": "aws_codedeploy_deployment_group",
    "AWS::CodeDeploy::DeploymentConfig": "aws_codedeploy_deployment_config",
    "AWS::ECR::Repository": "aws_ecr_repository",
    "AWS::ECR::RegistryPolicy": "aws_ecr_registry_policy",
    "AWS::ECR::ReplicationConfiguration": "aws_ecr_replication_configuration",
    # ==========================================================================
    # Analytics
    # ==========================================================================
    "AWS::Athena::WorkGroup": "aws_athena_workgroup",
    "AWS::Athena::DataCatalog": "aws_athena_data_catalog",
    "AWS::Athena::NamedQuery": "aws_athena_named_query",
    "AWS::Glue::Database": "aws_glue_catalog_database",
    "AWS::Glue::Table": "aws_glue_catalog_table",
    "AWS::Glue::Crawler": "aws_glue_crawler",
    "AWS::Glue::Job": "aws_glue_job",
    "AWS::Glue::Trigger": "aws_glue_trigger",
    "AWS::Glue::Connection": "aws_glue_connection",
    "AWS::Glue::SecurityConfiguration": "aws_glue_security_configuration",
    "AWS::EMR::Cluster": "aws_emr_cluster",
    "AWS::EMR::SecurityConfiguration": "aws_emr_security_configuration",
    "AWS::QuickSight::Analysis": "aws_quicksight_analysis",
    "AWS::QuickSight::Dashboard": "aws_quicksight_dashboard",
    "AWS::QuickSight::DataSet": "aws_quicksight_data_set",
    "AWS::QuickSight::DataSource": "aws_quicksight_data_source",
    "AWS::QuickSight::Group": "aws_quicksight_group",
    "AWS::QuickSight::User": "aws_quicksight_user",
    # ==========================================================================
    # Machine Learning
    # ==========================================================================
    "AWS::SageMaker::Endpoint": "aws_sagemaker_endpoint",
    "AWS::SageMaker::EndpointConfig": "aws_sagemaker_endpoint_configuration",
    "AWS::SageMaker::Model": "aws_sagemaker_model",
    "AWS::SageMaker::NotebookInstance": "aws_sagemaker_notebook_instance",
    "AWS::SageMaker::NotebookInstanceLifecycleConfig": "aws_sagemaker_notebook_instance_lifecycle_configuration",
    "AWS::SageMaker::Domain": "aws_sagemaker_domain",
    "AWS::SageMaker::UserProfile": "aws_sagemaker_user_profile",
    "AWS::SageMaker::FeatureGroup": "aws_sagemaker_feature_group",
    "AWS::Bedrock::Agent": "aws_bedrockagent_agent",
    "AWS::Bedrock::KnowledgeBase": "aws_bedrockagent_knowledge_base",
    # ==========================================================================
    # Application Integration
    # ==========================================================================
    "AWS::AppSync::GraphQLApi": "aws_appsync_graphql_api",
    "AWS::AppSync::DataSource": "aws_appsync_datasource",
    "AWS::AppSync::Resolver": "aws_appsync_resolver",
    "AWS::AppSync::FunctionConfiguration": "aws_appsync_function",
    "AWS::AppSync::ApiKey": "aws_appsync_api_key",
    "AWS::EventSchemas::Registry": "aws_schemas_registry",
    "AWS::EventSchemas::Schema": "aws_schemas_schema",
    "AWS::EventSchemas::Discoverer": "aws_schemas_discoverer",
}


def aws_to_terraform_type(aws_type: str) -> str | None:
    """
    Convert AWS CloudFormation resource type to Terraform resource type.

    Uses a comprehensive mapping table for accurate conversion. Returns
    None for unknown resource types rather than guessing incorrectly.

    Args:
        aws_type: AWS CloudFormation resource type (e.g., "AWS::S3::Bucket")

    Returns:
        Terraform resource type (e.g., "aws_s3_bucket") or None if unknown

    Examples:
        >>> aws_to_terraform_type("AWS::S3::Bucket")
        "aws_s3_bucket"
        >>> aws_to_terraform_type("AWS::ElasticLoadBalancingV2::LoadBalancer")
        "aws_lb"
        >>> aws_to_terraform_type("AWS::Unknown::Type")
        None
    """
    result = AWS_TO_TERRAFORM_TYPE_MAP.get(aws_type)

    if result is None:
        log_with_context(
            logger,
            "warning",
            "Unknown AWS resource type",
            aws_type=aws_type,
        )

    return result


def get_all_terraform_types_for_service(service: str) -> list[str]:
    """
    Get all Terraform resource types for an AWS service.

    Useful for fuzzy matching when the exact resource type is unknown.

    Args:
        service: AWS service name (e.g., "S3", "IAM", "EC2")

    Returns:
        List of Terraform resource types for that service

    Example:
        >>> get_all_terraform_types_for_service("S3")
        ["aws_s3_bucket", "aws_s3_bucket_policy", "aws_s3_access_point", ...]
    """
    prefix = f"AWS::{service}::"
    return [
        tf_type
        for aws_type, tf_type in AWS_TO_TERRAFORM_TYPE_MAP.items()
        if aws_type.startswith(prefix)
    ]


def get_supported_aws_types() -> list[str]:
    """
    Get list of all supported AWS CloudFormation types.

    Returns:
        Sorted list of all supported AWS resource types
    """
    return sorted(AWS_TO_TERRAFORM_TYPE_MAP.keys())


def is_supported_type(aws_type: str) -> bool:
    """
    Check if an AWS CloudFormation type is supported.

    Args:
        aws_type: AWS CloudFormation resource type

    Returns:
        True if the type has a known Terraform mapping
    """
    return aws_type in AWS_TO_TERRAFORM_TYPE_MAP
