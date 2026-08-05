import asyncio
import signal

import structlog

from app.core.database import AsyncSessionLocal
from app.services.scratch_card_service import ScratchCardService

logger = structlog.get_logger()
stopping = False


def stop_worker(*_args) -> None:
    global stopping
    stopping = True


async def run() -> None:
    signal.signal(signal.SIGINT, stop_worker)
    signal.signal(signal.SIGTERM, stop_worker)
    logger.info("scratch_card_worker.started")
    while not stopping:
        async with AsyncSessionLocal() as session:
            try:
                service = ScratchCardService(session)
                maintenance = await service.maintain_lifecycle()
                job_id = await service.process_next_job()
                await session.commit()
                if job_id:
                    logger.info("scratch_card_worker.job_processed", job_id=str(job_id))
                if any(maintenance.values()):
                    logger.info("scratch_card_worker.maintenance", **maintenance)
            except Exception:
                await session.rollback()
                logger.exception("scratch_card_worker.iteration_failed")
        if not stopping:
            await asyncio.sleep(2)
    logger.info("scratch_card_worker.stopped")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
