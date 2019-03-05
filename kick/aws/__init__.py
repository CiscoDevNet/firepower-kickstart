""" init for module kick.aws2 """
try:
    from kick.graphite.graphite import publish_kick_metric
except ImportError:
    from kick.metrics.metrics import publish_kick_metric
from .aws import Ec2, Vpc, Tester
from .aws import wait_until_ssh_ready

publish_kick_metric('aws.aws.import', 1)
