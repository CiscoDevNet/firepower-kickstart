
class Patterns:
    password_prompt = r'.*?[Pp]assword.*?: '
    prelogin_prompt = r'(?<!Last )login: '
    fireos_prompt = '\r\n[\x07]?> '
    user_prompt = '\r\n(.*@.*):~\$ '
    sudo_prompt = '[\r\n]?(root@.*#) '
