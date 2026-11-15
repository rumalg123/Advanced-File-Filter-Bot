"""Configured privileged users retain their bypass in the dedicated batch policy."""
from types import SimpleNamespace as NS

import pytest

from core.services.filestore import FileStoreService
from repositories.batch_link import BatchLink


@pytest.mark.parametrize('user_id',[1,42])
@pytest.mark.parametrize('premium_only',[False,True])
@pytest.mark.parametrize('enabled',[False,True])
@pytest.mark.parametrize('premium',[False,True])
@pytest.mark.asyncio
async def test_batch_policy_preserves_privileged_bypass_and_normal_rules(user_id,premium_only,enabled,premium):
    service=FileStoreService(None,None,NS(ADMINS=[1]))
    batch=BatchLink('qa',-1001,1,2,premium_only=premium_only)
    allowed,_=await service.check_premium_batch_access(batch,user_id,premium,enabled)
    expected=user_id==1 or (enabled and premium) or (not enabled and not premium_only)
    assert allowed is expected
