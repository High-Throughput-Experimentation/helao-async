"""OPC UA station and variable wrappers used by the LEANCAT driver.

:class:`Station` opens a single ``opcua`` client connection for a named
LEANCAT station, while :class:`Variable` wraps an individual node and
provides typed read/write plus favourite-flag toggling against the
LEANCAT ``opcVariables`` table.
"""

from typing import Any
from opcua import ua, Client, Node
from psycopg2 import sql
from ..database import query
from ..logger import script_log


# with open(arg_app_config_path, "r") as f:
#     app_config = json.loads(f.read())


class Variable:
    """Wrapper around an ``opcua.Node`` belonging to a named station.

    Holds the registered node, owning station name and node id so that
    favourite-flag updates can be applied against the LEANCAT database.
    """

    def __init__(self, node: Node, station_name: str, node_id: str) -> None:
        """Store the OPC node and the station/node identifiers.

        Args:
            node: The registered ``opcua.Node``.
            station_name: Owning LEANCAT station name.
            node_id: Identifier of the node within the OPC namespace.
        """
        self._node = node
        self._station_name = station_name
        self._node_id = node_id

    def set_value(self, value) -> None:
        """Write ``value`` to the underlying node using its variant type.

        Args:
            value: Python value to write.

        Raises:
            Exception: If the OPC write fails for any reason.
        """
        try:
            variant_type = self._node.get_data_type_as_variant_type()
            self._node.set_attribute(
                ua.AttributeIds.Value, ua.DataValue(ua.Variant(value, variant_type))
            )
            script_log.debug(
                f'Set value of variable with node id "{self._node.basenodeid}" to value: {value}'
            )
        except Exception as e:
            error_msg = f'Failed to set value of variable with node id: "{self._node.basenodeid}" to value: {value}, error message: {e}'
            raise Exception(error_msg)

    def get_value(self) -> Any:
        """Read and return the current value of the node.

        Raises:
            Exception: If the OPC read fails.
        """
        try:
            return self._node.get_value()
        except Exception as e:
            error_msg = f'Failed to read value of variable with node id: "{self._node.basenodeid}", error message: {e}'
            raise Exception(error_msg)

    def get_data_type(self) -> str:
        """Return the node's variant data type name without the prefix.

        Raises:
            Exception: If the data-type query fails.
        """
        try:
            variant_type = str(self._node.get_data_type_as_variant_type())
            # str converts the variant type enum including the prefix 'VariantType.' that is removed with [12:]
            return variant_type[12:]
        except Exception as e:
            error_msg = f'Failed to get data type of variable with node id: "{self._node.basenodeid}", error message: {e}'
            raise Exception(error_msg)

    def add_to_favorites(self) -> int:
        """Flag this variable as an export favourite in the LEANCAT DB.

        Returns:
            The id of the updated ``opcVariables`` row.
        """
        str_sql1 = sql.SQL(
            """SELECT "id" FROM "stations" WHERE "name" = {station_name}"""
        ).format(
            station_name=sql.Literal(self._station_name),
        )
        station_id = query(str_sql1)

        str_sql2 = sql.SQL(
            """UPDATE "opcVariables" SET "exportFavorite" = true WHERE "stationId" = '{stationId}' AND "nodeId" = {nodeId} RETURNING "id" """
        ).format(
            stationId=sql.Literal(station_id[0][0]),
            nodeId=sql.Literal(self._node_id),
        )
        res = query(str_sql2)
        script_log.debug(f"OPC variable with id: {res[0][0]} added to favorites ")
        return res[0][0]

    def remove_from_favorites(self) -> int:
        """Clear the export-favourite flag for this variable.

        Returns:
            The id of the updated ``opcVariables`` row.
        """
        str_sql1 = sql.SQL(
            """SELECT "id" FROM "stations" WHERE "name" = {station_name}"""
        ).format(
            station_name=sql.Literal(self._station_name),
        )
        station_id = query(str_sql1)

        str_sql2 = sql.SQL(
            """UPDATE "opcVariables" SET "exportFavorite" = false WHERE "stationId" = '{stationId}' AND "nodeId" = {nodeId} RETURNING "id" """
        ).format(
            stationId=sql.Literal(station_id[0][0]),
            nodeId=sql.Literal(self._node_id),
        )
        res = query(str_sql2)
        script_log.debug(f"OPC variable with id: {res[0][0]} removed from favorites ")
        return res[0][0]


class Station:
    """Connection wrapper for a single LEANCAT OPC UA station.

    Looks up the requested station's OPC connection options inside
    ``app_config['stations']`` and opens an ``opcua.Client`` against
    ``opc.tcp://<host>:<port>``.
    """

    def __init__(self, station_name: str, app_config: dict) -> None:
        """Load OPC connection options for ``station_name`` from ``app_config``.

        Args:
            station_name: Name of the LEANCAT station to configure.
            app_config: Parsed LEANCAT ``app.config.json`` dict.

        Raises:
            Exception: If no matching station is found in ``app_config``.
        """
        self._station_name = station_name
        self._connection_options = None
        self._client = None

        for station in app_config["stations"]:
            if station["name"] == station_name:
                self._connection_options = station["opc"]["connectionOptions"]
                # If two configurations with the same station name are found, read only the first one
                break

        if self._connection_options is None:
            raise Exception(
                f'Configuration for station with name "{station_name}" not found'
            )
        else:
            script_log.debug(
                f'Successfully loaded station configuration for station with name "{station_name}"'
            )

    def connect(self) -> Client:
        """Open the underlying ``opcua.Client`` connection.

        Returns:
            The connected :class:`opcua.Client` instance.

        Raises:
            Exception: If the OPC connection fails.
        """
        try:
            host = self._connection_options["host"]
            port = self._connection_options["port"]
            url = f"opc.tcp://{host}:{port}"
            self._client = Client(url)
            self._client.connect()
            script_log.debug(f'Station "{self._station_name}" connected')
            # #todo Set security policy based on the settings
            return self._client
        except Exception as e:
            raise Exception(
                f'Failed to connect to the station "{self._station_name}", error message: {e}'
            )

    def disconnect(self):
        """Disconnect the OPC client.

        Raises:
            Exception: If the OPC disconnect fails.
        """
        try:
            self._client.disconnect()
            script_log.debug(f'Station "{self._station_name}" disconnected')
        except Exception as e:
            raise Exception(
                f'Failed to disconnect from the station "{self._station_name}", error message: {e}'
            )

    def get_variable(self, node_id) -> Variable:
        """Resolve ``node_id`` on the server, register it and wrap it.

        The OPC node is registered with the client for faster subsequent
        reads/writes, and a :class:`Variable` is returned for convenient
        access.

        Args:
            node_id: OPC node identifier string.

        Returns:
            A :class:`Variable` bound to the registered node.

        Raises:
            Exception: If the node lookup or registration fails.
        """
        try:
            node = self._client.get_node(node_id)

            # Get the nodes data type to verify if the variables exists in the namespace of OPC UA server
            node.get_data_type_as_variant_type()

            # Register the node for faster read and write access
            nodes = []
            nodes.append(node)
            self._client.register_nodes(nodes)

            script_log.debug(f'Created variable with node id: "{node_id}"')

            return Variable(node, self._station_name, node_id)
        except Exception as e:
            script_log.error(
                f'Failed to create variable with node id: "{node_id}", error message: {e}'
            )
            raise Exception(e)

    def remove_all_from_favorites(self) -> None:
        """Clear the export-favourite flag on every variable for this station."""
        str_sql1 = sql.SQL(
            """SELECT "id" FROM "stations" WHERE "name" = {station_name}"""
        ).format(
            station_name=sql.Literal(self._station_name),
        )
        station_id = query(str_sql1)

        str_sql2 = sql.SQL(
            """UPDATE "opcVariables" SET "exportFavorite" = false WHERE "stationId" = '{stationId}' """
        ).format(
            stationId=sql.Literal(station_id[0][0]),
        )
        res = query(str_sql2)
        script_log.debug(
            f"All OPC variables with station id: {station_id[0][0]} removed from favorites"
        )
        return None
