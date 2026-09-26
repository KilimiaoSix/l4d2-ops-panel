from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, Field

from ..context import AppContext
from ..deps import current_account, get_ctx, require_owner

router = APIRouter()


class OnboardingIn(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    step: str | None = None
    draft: dict = Field(default_factory=dict)
    complete: bool = False
    reopen: bool = False


@router.get('/api/onboarding')
def get_state(response: Response, ctx: AppContext = Depends(get_ctx), account: dict = Depends(current_account)):
    response.headers['Cache-Control'] = 'no-store'
    return ctx.onboarding.get()


@router.post('/api/onboarding')
def save_state(body: OnboardingIn, response: Response, ctx: AppContext = Depends(get_ctx), owner: dict = Depends(require_owner)):
    response.headers['Cache-Control'] = 'no-store'
    return ctx.onboarding.save(body.step, body.draft, body.complete, body.reopen, owner['username'])
