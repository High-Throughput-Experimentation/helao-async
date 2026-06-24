# shell: uvicorn motion_server:app --reload
"""FastAPI action server for a KD Scientific Legato syringe pump.

Wraps the :class:`KDS100` driver and :class:`PumpExec` executor and exposes
action endpoints for infusing, withdrawing, and querying the dispensed
volume, plus private endpoints for direct pump control.
"""

__all__ = ["makeApp"]


from fastapi import Body

from ...drivers.pump.legato_driver import KDS100, PumpExec
from helao.framework.app.base_api import BaseAPI
from helao.framework.domain.run_models import Action
from helao.framework.models.data import DataModel
from helao.framework.models.errors import ErrorCodes


def makeApp(server_key) -> BaseAPI:
    """Build the BaseAPI app for the KDS100 syringe pump.

    Args:
        server_key: Unique key identifying this server in the orchestration
            group.

    Returns:
        The configured BaseAPI instance with infuse/withdraw and volume
        bookkeeping endpoints registered.
    """

    app = BaseAPI(
        server_key=server_key,
        server_title=server_key,
        description="Syringe pump server",
        version=2.0,
        driver_classes=[KDS100],
    )

    @app.post("/start_polling", tags=["private"])
    async def start_polling():
        """Start the driver's background polling loop."""
        await app.driver.start_polling()

    @app.post("/stop_polling", tags=["private"])
    async def stop_polling():
        """Stop the driver's background polling loop."""
        await app.driver.stop_polling()

    @app.post(f"/{server_key}/infuse", tags=["action"])
    async def infuse(
        rate_uL_sec: int = 0,
        volume_uL: int = 0,
    ):
        """Dispense ``volume_uL`` at ``rate_uL_sec`` in the infuse direction.

        Args:
            action: Action wrapper supplied by the orchestrator.
            action_version: Schema version for this endpoint.
            rate_uL_sec: Flow rate in microlitres per second.
            volume_uL: Total volume to dispense in microlitres.

        Returns:
            The active action dictionary from ``start_executor``.
        """
        active = await app.base.setup_and_contain_action()
        executor = PumpExec(direction=1, active=active, oneoff=False, poll_rate=0.2)
        active_action_dict = active.start_executor(executor)
        return active_action_dict

    @app.post(f"/{server_key}/withdraw", tags=["action"])
    async def withdraw(
        rate_uL_sec: int = 0,
        volume_uL: int = 0,
    ):
        """Aspirate ``volume_uL`` at ``rate_uL_sec`` in the withdraw direction.

        Args:
            action: Action wrapper supplied by the orchestrator.
            action_version: Schema version for this endpoint.
            rate_uL_sec: Flow rate in microlitres per second.
            volume_uL: Total volume to draw in microlitres.

        Returns:
            The active action dictionary from ``start_executor``.
        """
        active = await app.base.setup_and_contain_action()
        executor = PumpExec(direction=-1, active=active, oneoff=False, poll_rate=0.2)
        active_action_dict = active.start_executor(executor)
        return active_action_dict

    @app.post(f"/{server_key}/get_present_volume", tags=["action"])
    async def get_present_volume(
    ):
        """Read and record the driver's tracked syringe volume.

        Enqueues a data row with the current ``present_volume_ul`` and stores
        the value back into ``action_params['_present_volume_ul']``.

        Args:
            action: Action wrapper supplied by the orchestrator.
            action_version: Schema version for this endpoint.

        Returns:
            The finished action dictionary.
        """
        active = await app.base.setup_and_contain_action()
        present_volume = app.driver.present_volume_ul
        datadict = {"present_volume_ul": present_volume, "error_code": ErrorCodes.none}
        datamodel = DataModel(data={active.base.dflt_file_conn_key(): datadict})
        active.action.action_params.update({"_present_volume_ul": present_volume})
        active.enqueue_data_nowait(datamodel, action=active.action)
        finished_action = await active.finish()
        return finished_action.as_dict()

    @app.post(f"/set_present_volume", tags=["private"])
    async def set_present_volume(volume_uL: float = 0) -> dict:
        """Overwrite the driver's tracked ``present_volume_ul`` value."""
        app.driver.present_volume_ul = volume_uL
        return {"present_volume_ul": volume_uL}

    @app.post(f"/get_present_volume", tags=["private"])
    async def get_present_volume_priv() -> dict:
        """Return the driver's currently tracked ``present_volume_ul``."""
        return {"present_volume_ul": app.driver.present_volume_ul}

    @app.post("/set_rate", tags=["private"])
    async def set_rate(pump_name: str, rate_uL_sec: int, direction: int):
        """Set pump rate by name and direction; delegates to the driver."""
        return await app.driver.set_rate(pump_name, rate_uL_sec, direction)

    @app.post("/set_target_volume", tags=["private"])
    async def set_target_volume(pump_name: str, volume_uL: int):
        """Set the target dispense volume on the named pump."""
        return await app.driver.set_target_volume(pump_name, volume_uL)

    @app.post("/start_pump", tags=["private"])
    async def start_pump(pump_name: str, direction: int):
        """Start the named pump in the given direction."""
        return await app.driver.start_pump(pump_name, direction)

    @app.post("/stop_pump", tags=["private"])
    async def stop_pump(pump_name: str):
        """Stop the named pump."""
        return await app.driver.stop_pump(pump_name)

    @app.post("/clear_volume", tags=["private"])
    async def clear_volume(pump_name: str):
        """Clear the cumulative volume counter on the named pump."""
        return await app.driver.clear_volume(pump_name)

    @app.post("/clear_target_volume", tags=["private"])
    async def clear_target_volume(pump_name: str):
        """Clear the target volume setting on the named pump."""
        return await app.driver.clear_target_volume(pump_name)

    return app
