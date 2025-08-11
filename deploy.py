import os, time, boto3

region = os.getenv("DEPLOY_REGION", "us-east-1")
bucket = os.getenv("ARTIFACT_BUCKET")
prefix = os.getenv("ARTIFACT_PREFIX", "artifacts")
tag_key = os.getenv("DEPLOY_TAG_KEY", "App")
tag_val = os.getenv("DEPLOY_TAG_VALUE", "CICDRoadmap")
webroot = os.getenv("WEBROOT", "/var/www/html")

ssm = boto3.client("ssm", region_name=region)
ec2 = boto3.client("ec2", region_name=region)

# Find running instances by tag
resp = ec2.describe_instances(
    Filters=[
        {"Name": f"tag:{tag_key}", "Values": [tag_val]},
        {"Name": "instance-state-name", "Values": ["running"]},
    ]
)
instance_ids = [i["InstanceId"] for r in resp["Reservations"] for i in r["Instances"]]
if not instance_ids:
    raise SystemExit(f"No running instances with {tag_key}={tag_val}")

s3_uri = f"s3://{bucket}/{prefix}/build.zip"
commands = [
    f"sudo mkdir -p {webroot}",
    f"cd /tmp && aws s3 cp {s3_uri} build.zip",
    "cd /tmp && rm -rf deploy_tmp && mkdir -p deploy_tmp && unzip -o build.zip -d deploy_tmp",
    f"sudo cp -r /tmp/deploy_tmp/* {webroot}/",
    "sudo chown -R root:root /var/www/html",
    "sudo systemctl restart httpd || sudo systemctl start httpd",
]

send = ssm.send_command(
    InstanceIds=instance_ids,
    DocumentName="AWS-RunShellScript",
    Parameters={"commands": commands},
    TimeoutSeconds=600,
)
cmd_id = send["Command"]["CommandId"]

# Wait for success
done = set()
while len(done) < len(instance_ids):
    time.sleep(3)
    inv = ssm.list_command_invocations(CommandId=cmd_id, Details=True)
    for item in inv.get("CommandInvocations", []):
        iid, status = item["InstanceId"], item["Status"]
        if iid not in done and status in ("Success","Cancelled","TimedOut","Failed"):
            print(f"{iid}: {status}")
            done.add(iid)

final = ssm.list_command_invocations(CommandId=cmd_id, Details=True)
statuses = [i["Status"] for i in final.get("CommandInvocations", [])]
if not statuses or any(s != "Success" for s in statuses):
    raise SystemExit(f"SSM deploy not successful: {statuses}")
print("Deploy completed to:", instance_ids)
