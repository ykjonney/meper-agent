"""PEP 562 entry: importing this package triggers registration of all
built-in adapters via their @ChannelRegistry.register decorators.

Adding a new platform = create providers/<name>/ + add one import line here.
ChannelRegistry itself never needs editing.
"""
# Following adapters added in later tasks:
from . import (
    dingtalk,  # noqa: F401
    lark,  # noqa: F401
    mock,  # noqa: F401
    wecom,  # noqa: F401
)
