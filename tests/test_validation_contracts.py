"""Input, permissions and premium boundaries used by Telegram entry points."""
from datetime import UTC,datetime,timedelta,timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock,Mock

import pytest
from pyrogram import enums
from pyrogram.types import Message,CallbackQuery

from core.utils.validators import (ValidationUtils,PermissionUtils,AccessControl,
    PremiumValidation,InputValidation,ValidationDecorators)


@pytest.mark.parametrize('value,valid,parsed',[(12,True,12),('12',True,12),('@12',True,12),
    ('0',False,None),(0,False,None),(-2,False,None),('hello',False,None),(None,False,None),([],False,None)])
def test_user_id_input_boundaries(value,valid,parsed):
    allowed,user_id,error=ValidationUtils.validate_user_id(value)
    assert allowed is valid and user_id==parsed
    assert (error is None)==valid


@pytest.mark.parametrize('page,size,valid',[('2','20',True),(1,100,True),(0,10,False),
    (-1,10,False),(1,0,False),(1,101,False),('bad',10,False)])
def test_pagination_boundaries(page,size,valid):
    result=ValidationUtils.validate_pagination_params(page,size)
    assert result[0] is valid
    if valid:assert result[1:3]==(int(page),int(size))
    else:assert result[1:3]==(0,0)


@pytest.mark.parametrize('types,expected', [([],[]),([' Video ','AUDIO'],['video','audio']),
    (['photo','contact','voice','video_note','animation','sticker','location'],
     ['photo','contact','voice','video_note','animation','sticker','location'])])
def test_file_type_normalization(types,expected):
    assert ValidationUtils.validate_file_types(types)==(True,expected,None)


def test_unsupported_file_type_is_rejected():
    allowed,types,error=ValidationUtils.validate_file_types(['executable'])
    assert not allowed and types==[] and 'executable' in error


@pytest.mark.parametrize('callback',[False,True])
@pytest.mark.parametrize('kind',[enums.ChatType.PRIVATE,enums.ChatType.SUPERGROUP,enums.ChatType.GROUP])
def test_telegram_identity_and_chat_classification(callback,kind):
    obj=Mock(spec=CallbackQuery if callback else Message)
    obj.from_user=SimpleNamespace(id=12,is_bot=False)
    chat=SimpleNamespace(id=-10012,type=kind)
    if callback:obj.message=SimpleNamespace(chat=chat)
    else:obj.chat=chat
    assert ValidationUtils.extract_user_id(obj)==12
    assert ValidationUtils.is_private_chat(obj)==(kind==enums.ChatType.PRIVATE)
    assert ValidationUtils.is_group_chat(obj)==(kind!=enums.ChatType.PRIVATE)
    assert not ValidationUtils.is_bot_user(obj)
    obj.from_user=None
    assert ValidationUtils.extract_user_id(obj) is None
    assert not ValidationUtils.is_bot_user(obj)


@pytest.mark.asyncio
@pytest.mark.parametrize('status,admin,owner',[(enums.ChatMemberStatus.OWNER,True,True),
    (enums.ChatMemberStatus.ADMINISTRATOR,True,False),(enums.ChatMemberStatus.MEMBER,False,False)])
async def test_remote_group_permissions_preserve_owner_admin_distinction(monkeypatch,status,admin,owner):
    monkeypatch.setattr('core.utils.validators.telegram_api.call_api',AsyncMock(return_value=SimpleNamespace(status=status)))
    client=SimpleNamespace(get_chat_member=AsyncMock())
    assert await PermissionUtils.is_group_admin(client,-10012,12) is admin
    assert await PermissionUtils.is_group_owner(client,-10012,12) is owner
    assert await PermissionUtils.has_admin_rights(client,-10012,12,[]) is admin
    assert await PermissionUtils.is_owner_or_bot_admin(client,-10012,12,[]) is owner
    assert await PermissionUtils.has_admin_rights(client,-10012,12,[12])
    assert await PermissionUtils.is_owner_or_bot_admin(client,-10012,12,[12])


@pytest.mark.asyncio
async def test_group_permission_transport_failures_deny(monkeypatch):
    monkeypatch.setattr('core.utils.validators.telegram_api.call_api',AsyncMock(side_effect=ConnectionError('QA offline')))
    client=SimpleNamespace(get_chat_member=AsyncMock())
    assert not await PermissionUtils.is_group_admin(client,-10012,12)
    assert not await PermissionUtils.is_group_owner(client,-10012,12)


@pytest.mark.parametrize('delta,flag,valid',[(1,True,True),(0,True,False),(-1,True,False),(1,False,False)])
def test_premium_expiry_exact_boundary(delta,flag,valid):
    now=datetime(2026,10,29,tzinfo=UTC);expiry=now+timedelta(seconds=delta)
    assert PremiumValidation.is_premium_valid(flag,expiry,now) is valid
    assert PremiumValidation.get_days_remaining(expiry,now)==(1 if delta>0 else 0)
    assert PremiumValidation.normalize_expiry_date(expiry.replace(tzinfo=None))==expiry
    assert PremiumValidation.normalize_expiry_date(expiry.astimezone(timezone(timedelta(hours=5,minutes=30))))==expiry


def test_absent_premium_state_has_no_entitlement():
    assert not PremiumValidation.is_premium_valid(True,None)
    assert PremiumValidation.check_user_premium_status(None)==(False,None)
    assert PremiumValidation.get_days_remaining(None)==0
    assert PremiumValidation.normalize_expiry_date(None) is None
    assert not PremiumValidation.check_user_premium_status(SimpleNamespace())[0]


@pytest.mark.parametrize('raw,expected',[('bad<name>:a/b\\c|?*\x00','bad_name__a_b_c___'),('', ''),('a'*300,'a'*255)])
def test_filename_sanitization(raw,expected):
    assert InputValidation.sanitize_filename(raw)==expected


@pytest.mark.parametrize('raw,expected',[('  qa\x00   title  ','qa title'),('', ''),('a'*120,'a'*100)])
def test_search_input_sanitization(raw,expected):
    assert InputValidation.sanitize_search_query(raw)==expected


def test_caption_and_command_input_boundaries():
    assert InputValidation.sanitize_caption('a\x00b')=='ab'
    assert InputValidation.sanitize_caption('')==''
    assert len(InputValidation.sanitize_caption('a'*1100))==1024
    assert InputValidation.extract_command_args(SimpleNamespace(text=None))==(False,[])
    assert InputValidation.extract_command_args(SimpleNamespace(text='/cmd'))==(True,[])
    assert InputValidation.extract_command_args(SimpleNamespace(text='/cmd a b'),max_args=1)==(False,['a','b'])
    assert InputValidation.extract_command_args(SimpleNamespace(text='/cmd a'),min_args=2)==(False,['a'])
    assert InputValidation.extract_command_args(SimpleNamespace(text='/cmd a b'))==(True,['a','b'])
    assert InputValidation.validate_callback_data(SimpleNamespace(data=None))==(False,[])
    assert InputValidation.validate_callback_data(SimpleNamespace(data='one'))==(False,['one'])
    assert InputValidation.validate_callback_data(SimpleNamespace(data='one#two'))==(True,['one','two'])
    assert InputValidation.normalize_query(' Doctor.X_  Mafia+ ' )=='doctor x mafia'
    assert InputValidation.normalize_filename_for_search('Doctor.X_Mafia+')=='Doctor X Mafia'


@pytest.mark.asyncio
@pytest.mark.parametrize('reason,user',[('Banned',None),('Daily limit reached',None),
    ('Daily limit reached',SimpleNamespace(daily_retrieval_count=10))])
async def test_file_access_denial_uses_callback_safe_text(reason,user):
    repo=SimpleNamespace(can_retrieve_file=AsyncMock(return_value=(False,reason)),
        get_user=AsyncMock(return_value=user),daily_limit=10)
    query=Mock(spec=CallbackQuery);query.answer=AsyncMock()
    assert not await AccessControl.validate_file_access(repo,12,query)
    assert '<b>' not in query.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_file_access_handles_service_failure_and_allowed_message():
    repo=SimpleNamespace(can_retrieve_file=AsyncMock(side_effect=ConnectionError('QA')))
    allowed,reason=await AccessControl.can_access_file(repo,12)
    assert not allowed and 'Error' in reason
    repo.can_retrieve_file=AsyncMock(return_value=(True,'allowed'))
    assert await AccessControl.validate_file_access(repo,12,SimpleNamespace())
    repo.can_retrieve_file.return_value=(False,'denied')
    msg=Mock(spec=Message);msg.reply_text=AsyncMock()
    assert not await AccessControl.validate_file_access(repo,12,msg)
    msg.reply_text.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize('data,allowed,owner',[('file#id#12',True,12),('file#id#13',False,13),('legacy#id',True,None)])
async def test_callback_owner_binding(data,allowed,owner):
    query=Mock(spec=CallbackQuery);query.from_user=SimpleNamespace(id=12)
    query.data=data;query.answer=AsyncMock()
    assert await AccessControl.validate_original_requester(query)==(allowed,12,owner)
