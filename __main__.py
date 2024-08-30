import pulumi
import pulumi_aws as aws
import json

# Create a VPC for our cluster
vpc = aws.ec2.Vpc("eks-vpc",
    cidr_block="10.0.0.0/16",
    instance_tenancy="default",
    enable_dns_hostnames=True,
    enable_dns_support=True,
    tags={"Name": "eks-vpc"}
)

# Create an internet gateway
igw = aws.ec2.InternetGateway("eks-igw",
    vpc_id=vpc.id,
    tags={"Name": "eks-igw"}
)

# Create two public subnets
public_subnet_1 = aws.ec2.Subnet("eks-public-subnet-1",
    vpc_id=vpc.id,
    cidr_block="10.0.1.0/24",
    availability_zone="us-east-1a",
    map_public_ip_on_launch=True,
    tags={"Name": "eks-public-subnet-1"}
)

public_subnet_2 = aws.ec2.Subnet("eks-public-subnet-2",
    vpc_id=vpc.id,
    cidr_block="10.0.2.0/24",
    availability_zone="us-east-1b",
    map_public_ip_on_launch=True,
    tags={"Name": "eks-public-subnet-2"}
)

# Create a route table and associate it with the public subnets
public_route_table = aws.ec2.RouteTable("eks-public-rt",
    vpc_id=vpc.id,
    routes=[aws.ec2.RouteTableRouteArgs(
        cidr_block="0.0.0.0/0",
        gateway_id=igw.id,
    )],
    tags={"Name": "eks-public-rt"}
)

aws.ec2.RouteTableAssociation("eks-rta-1",
    subnet_id=public_subnet_1.id,
    route_table_id=public_route_table.id
)

aws.ec2.RouteTableAssociation("eks-rta-2",
    subnet_id=public_subnet_2.id,
    route_table_id=public_route_table.id
)

# Create an EKS cluster
eks_role = aws.iam.Role("eks-role",
    assume_role_policy=json.dumps({
        "Version": "2012-10-17",
        "Statement": [{
            "Action": "sts:AssumeRole",
            "Effect": "Allow",
            "Principal": {
                "Service": "eks.amazonaws.com"
            }
        }]
    })
)

aws.iam.RolePolicyAttachment("eks-policy",
    role=eks_role.name,
    policy_arn="arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"
)

eks_cluster = aws.eks.Cluster("eks-cluster",
    role_arn=eks_role.arn,
    version="1.24",
    vpc_config=aws.eks.ClusterVpcConfigArgs(
        subnet_ids=[public_subnet_1.id, public_subnet_2.id],
    ),
    tags={"Name": "eks-cluster"}
)

# Create an IAM role for the node group
node_group_role = aws.iam.Role("eks-node-group-role",
    assume_role_policy=json.dumps({
        "Version": "2012-10-17",
        "Statement": [{
            "Action": "sts:AssumeRole",
            "Effect": "Allow",
            "Principal": {
                "Service": "ec2.amazonaws.com"
            }
        }]
    })
)

aws.iam.RolePolicyAttachment("eks-node-group-policy-AmazonEKSWorkerNodePolicy",
    role=node_group_role.name,
    policy_arn="arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy"
)

aws.iam.RolePolicyAttachment("eks-node-group-policy-AmazonEKS_CNI_Policy",
    role=node_group_role.name,
    policy_arn="arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy"
)

aws.iam.RolePolicyAttachment("eks-node-group-policy-AmazonEC2ContainerRegistryReadOnly",
    role=node_group_role.name,
    policy_arn="arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
)

# Create a node group
node_group = aws.eks.NodeGroup("eks-node-group",
    cluster_name=eks_cluster.name,
    node_role_arn=node_group_role.arn,
    subnet_ids=[public_subnet_1.id, public_subnet_2.id],
    scaling_config=aws.eks.NodeGroupScalingConfigArgs(
        desired_size=2,
        max_size=2,
        min_size=1
    ),
    instance_types=["t3.medium"],
    tags={"Name": "eks-node-group"}
)

# Create an OIDC provider for the cluster
oidc_provider = aws.iam.OpenIdConnectProvider("eks-oidc",
    client_id_lists=["sts.amazonaws.com"],
    thumbprint_lists=["9e99a48a9960b14926bb7f3b02e22da2b0ab7280"],
    url=eks_cluster.identities[0].oidcs[0].issuer
)

# Create an IAM role for pod execution with IRSA
pod_role = aws.iam.Role("pod-execution-role",
    assume_role_policy=pulumi.Output.all(oidc_provider.url, oidc_provider.arn).apply(
        lambda args: json.dumps({
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Principal": {
                    "Federated": args[1]
                },
                "Action": "sts:AssumeRoleWithWebIdentity",
                "Condition": {
                    "StringEquals": {
                        f"{args[0]}:sub": "system:serviceaccount:default:example-sa"
                    }
                }
            }]
        })
    )
)

# Attach a minimal policy to the pod role (adjust as needed)
aws.iam.RolePolicyAttachment("pod-execution-role-policy",
    role=pod_role.name,
    policy_arn="arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy"
)

# Export the cluster name and kubeconfig
pulumi.export("cluster-name", eks_cluster.name)
pulumi.export("cluster endpoint", eks_cluster.endpoint)
pulumi.export("cluster certificate authorty", eks_cluster.certificate_authority)
pulumi.export("cluster role arn", eks_role.arn)
pulumi.export("pod role name", pod_role.name)

# Run: aws eks update-kubeconfig --name <cluster-name> --region us-west-2
# Run: kubectl get nodes
