"""PH-022: shared confirmed/uncertain file-delivery quota settlement.

The optional tokenized ledger is authoritative when enabled. Legacy integer
reservations retain the existing release path for backwards compatibility.
"""
import asyncio


async def settle_delivery_quota(
    user_repo, user_id: int, reservation: int, confirmed_count: int,
    *, uncertain: bool = False
) -> bool:
    """Persist one settlement, preserving the original quota day and token.

    Cancellation during the outer send handler is not allowed to cancel a
    started ledger write, though process death still needs operator review.
    """
    if not reservation:
        return True
    if not isinstance(confirmed_count, int) or not 0 <= confirmed_count <= int(reservation):
        raise ValueError("Invalid confirmed file delivery count")
    token = getattr(reservation, 'reservation_id', None)
    if token and hasattr(user_repo, 'settle_quota_delivery'):
        return await asyncio.shield(user_repo.settle_quota_delivery(
            user_id, reservation, confirmed_count, uncertain=uncertain
        ))
    # Legacy behavior was an automatic refund for every unconfirmed send.
    # Do not silently turn it into a new policy without opt-in.
    unused = reservation - confirmed_count
    if unused > 0:
        return await asyncio.shield(user_repo.release_quota(user_id, unused))
    return True
