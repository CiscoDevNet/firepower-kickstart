

def publish_kick_metric(
        metric_name,
        value,
        moment=None,
        user=None,
        host_name=None):
    """Publish a KICK!

    metric based on its name and value. If moment is not set, use the
    current time. If user is not set, determine it with _get_username().
    If host_name is not set, determine it with __get_host_hostname().
    The structure of the resulting metric:
    kick.<user>.<host_name>.<metric_name>

    """
    pass
