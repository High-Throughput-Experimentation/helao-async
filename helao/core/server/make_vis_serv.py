from helao.core.server import HelaoBokehAPI, Vis


def makeVisServ(
    config,
    server_key,
    doc,
    server_title,
    description,
    version,
    driver_class=None,
):
    app = HelaoBokehAPI(
        config,
        server_key,
        doc=doc,
        title=server_title,
        description=description,
        ersion=version,
    )
    app.vis = Vis(app)
    return app
