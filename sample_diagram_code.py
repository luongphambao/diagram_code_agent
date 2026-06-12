import os
import shutil
from pathlib import Path

from diagrams import Diagram, Cluster, Edge, Node
from diagrams.aws.security import IAM, IdentityAndAccessManagementIam, Shield, Guardduty, WAF, SecretsManager
from diagrams.aws.management import Organizations, Cloudtrail, Cloudwatch, SystemsManager, TrustedAdvisor, Config
from diagrams.aws.network import ALB, NATGateway, ClientVpn, CloudFront, VPC, InternetGateway, Endpoint
from diagrams.aws.compute import EKS, ECR
from diagrams.aws.database import RDS
from diagrams.aws.storage import S3
from diagrams.aws.integration import Eventbridge, SQS
from diagrams.aws.devtools import Codebuild
from diagrams.onprem.ci import GithubActions
from diagrams.onprem.gitops import ArgoCD
from diagrams.onprem.vcs import Github
from diagrams.onprem.monitoring import Datadog, Splunk
from diagrams.aws.general import Users
from diagrams.onprem.client import Users as DevOpsUsers

# Define some custom colors for better visualization
COLOR_MANAGEMENT = "#009688"  # Teal
COLOR_DEV = "#03A9F4"         # Light Blue
COLOR_STAGING = "#FFC107"     # Amber
COLOR_PROD = "#F44336"        # Red
COLOR_NETWORK = "#8BC34A"     # Light Green
COLOR_COMPUTE = "#673AB7"     # Deep Purple
COLOR_DATABASE = "#FF9800"    # Orange
COLOR_FRONTEND = "#9C27B0"    # Purple
COLOR_CICD = "#795548"        # Brown
COLOR_MONITORING = "#607D8B"  # Blue Grey
COLOR_SECURITY = "#FF5722"    # Deep Orange
COLOR_USER = "#000000"        # Black

OUTPUT_STEM = Path(__file__).resolve().with_name("sample_diagram")
GRAPHVIZ_BIN = Path(r"C:\Program Files\Graphviz\bin")

if shutil.which("dot") is None and GRAPHVIZ_BIN.exists():
    os.environ["PATH"] = f"{GRAPHVIZ_BIN}{os.pathsep}{os.environ.get('PATH', '')}"

with Diagram(
    "Innovate Inc. Cloud Architecture",
    filename=str(OUTPUT_STEM),
    show=False,
    direction="TB",
    outformat=["png"],
):
    # External Users
    end_users = Users("End Users")
    admin = Users("Admin")
    
    # GitHub (External)
    with Cluster("GitHub (External)", graph_attr={"bgcolor": COLOR_CICD + "20"}):
        github = Github("Source Code")
        ci_cd = GithubActions("CI/CD Pipelines")
        
        github >> Edge(color=COLOR_CICD) >> ci_cd
        admin >> Edge(color=COLOR_USER, label="Push Code") >> github
    
    # Management Account (Master Account)
    with Cluster("Management Account", graph_attr={"bgcolor": COLOR_MANAGEMENT + "10"}):
        orgs = Organizations("AWS Organizations")
        
        with Cluster("Centralized Management"):
            iam_identity = IdentityAndAccessManagementIam("IAM Identity Center")
            
            with Cluster("Security Services", graph_attr={"bgcolor": COLOR_SECURITY + "20"}):
                guard_duty = Guardduty("GuardDuty")
                trails = Cloudtrail("CloudTrail")
                security_hub = Shield("Security Hub")
                aws_config = Config("AWS Config")
                trusted_advisor = TrustedAdvisor("Trusted Advisor")
                secrets = SecretsManager("Secrets Manager")
                
                # Connect security services
                guard_duty - trails - security_hub
                aws_config - trusted_advisor
                secrets - security_hub

            with Cluster("Monitoring & Logs", graph_attr={"bgcolor": COLOR_MONITORING + "20"}):
                logs = Cloudwatch("CloudWatch Logs")
                metrics = Cloudwatch("CloudWatch Metrics")
                ssm = SystemsManager("Systems Manager")
                
                # Connect logging services
                logs - metrics - ssm
    
    # Third-party Monitoring (External to AWS)
    with Cluster("Third-Party Monitoring", graph_attr={"bgcolor": COLOR_MONITORING + "10"}):
        datadog = Datadog("Datadog\nMonitoring")
        splunk = Splunk("Splunk\nLog Analytics")
        
        # Connect monitoring
        datadog - splunk
    
    # Production Account
    with Cluster("Production Account", graph_attr={"bgcolor": COLOR_PROD + "10"}):
        prod_account = Node("Account")
        prod_ecr = ECR("ECR Registry")
        prod_vpn = ClientVpn("Production VPN")
        prod_cwlogs = Cloudwatch("CloudWatch\nLogs & Metrics")
        prod_secrets = SecretsManager("Secrets Manager")
        
        # Static Frontend Hosting in Production
        with Cluster("Static Frontend Hosting", graph_attr={"bgcolor": COLOR_FRONTEND + "20"}):
            prod_frontend_s3 = S3("S3 Bucket\n(React SPA)")
            prod_frontend_cf = CloudFront("CloudFront CDN")
            prod_frontend_cf >> Edge(color=COLOR_FRONTEND) >> prod_frontend_s3
            end_users >> Edge(color=COLOR_USER, label="Web\nAccess") >> prod_frontend_cf
        
        with Cluster("VPC", graph_attr={"bgcolor": COLOR_NETWORK + "20"}):
            prod_igw = InternetGateway("Internet Gateway")
            
            with Cluster("Public Subnets"):
                prod_alb = ALB("Load Balancer")
                prod_nat = NATGateway("NAT Gateway")
            
            with Cluster("Private Subnets"):
                with Cluster("VPC Endpoints", graph_attr={"bgcolor": COLOR_NETWORK + "30"}):
                    prod_ecr_endpoint = Endpoint("ECR API")
                    prod_ecr_dkr_endpoint = Endpoint("ECR DKR")
                    prod_s3_endpoint = Endpoint("S3")
                
                with Cluster("Compute", graph_attr={"bgcolor": COLOR_COMPUTE + "20"}):
                    prod_eks = EKS("EKS Cluster")
                    
                    with Cluster("In-Cluster Services"):
                        prod_argo = ArgoCD("ArgoCD")
                        prod_eso = Node("External\nSecrets\nOperator")
                        prod_argo - prod_eso
                        prod_eso >> Edge(color=COLOR_SECURITY, style="dashed", label="Pull Secrets") >> prod_secrets
                
                with Cluster("Data", graph_attr={"bgcolor": COLOR_DATABASE + "20"}):
                    prod_rds = RDS("PostgreSQL")
    
    # Event Bus for Log Integration
    event_bridge = Eventbridge("EventBridge")
    log_queue = SQS("Log Queue")
    
    # Connect GitHub Actions to AWS Resources - Building and Pushing Images
    ci_cd >> Edge(color=COLOR_CICD, label="Build &\nPush Images") >> prod_ecr
    
    # Connect GitHub to ArgoCD instances
    github >> Edge(color=COLOR_CICD) >> prod_argo
    
    # Connect ECR to EKS via VPC Endpoints
    prod_ecr >> Edge(label="Pull\nImages") >> prod_ecr_endpoint >> prod_eks
    
    # Management Account Connections to Account Clusters
    orgs >> Edge(color=COLOR_MANAGEMENT, label="Manage") >> prod_account
    
    # Production Account Connections - ALB only
    end_users >> Edge(color=COLOR_USER, label="API Access") >> prod_alb
    prod_alb >> prod_eks
    prod_eks >> prod_rds
    
    # Connect CloudWatch to Resources
    prod_eks >> Edge(color=COLOR_MONITORING, label="Logs &\nMetrics") >> prod_cwlogs
    
    # Connect CloudWatch to Central Logging
    prod_cwlogs >> Edge(color=COLOR_MONITORING, label="Centralized\nLogging") >> logs
    
    # Connect EKS Pods to Splunk
    prod_eks >> Edge(color=COLOR_MONITORING, style="dashed", label="Pod\nLogs") >> event_bridge >> log_queue >> splunk
    
    # Connect Resources to Datadog Monitoring
    datadog >> Edge(color=COLOR_MONITORING, style="dashed", label="Monitor\nMetrics") >> prod_eks
    datadog >> Edge(color=COLOR_MONITORING, style="dashed", label="Monitor\nMetrics") >> prod_rds
    
    # Connect Security Services to Resources
    guard_duty >> Edge(color=COLOR_SECURITY, style="dotted", label="Security\nMonitoring") >> prod_eks

    # Admin VPN Access
    admin >> Edge(color=COLOR_USER, label="VPN\nAccess") >> prod_vpn
    prod_vpn >> Edge(color=COLOR_USER) >> prod_eks

    # IAM Identity Center Connections
    admin >> Edge(color=COLOR_USER, label="SSO Login") >> iam_identity
    iam_identity >> Edge(color=COLOR_MANAGEMENT, label="Identity\nFederation") >> prod_account

print(f"Generated diagram: {OUTPUT_STEM.with_suffix('.png')}")
