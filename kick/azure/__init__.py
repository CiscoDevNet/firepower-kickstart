from kick.azure.azure_lib import *
try:
    from kick.graphite.graphite import publish_kick_metric
except ImportError:
    from kick.metrics.metrics import publish_kick_metric

publish_kick_metric('azure.azure.import', 1)
