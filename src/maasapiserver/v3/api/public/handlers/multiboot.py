# Copyright 2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from typing import Union

from fastapi import Depends, Header, Response, status

from maasapiserver.common.api.base import Handler, handler
from maasapiserver.common.api.models.responses.errors import (
    ConflictBodyResponse,
    PreconditionFailedBodyResponse,
    UnauthorizedBodyResponse,
)
from maasapiserver.v3.api import services
from maasapiserver.v3.api.public.models.requests.multiboot import (
    SetLayoutRequest,
)
from maasapiserver.v3.api.public.models.responses.multiboot import (
    MultiBootDeploymentResponse,
    MultiBootDeploymentListResponse,
)
from maasapiserver.v3.auth.base import (
    check_permissions,
    get_authenticated_user,
)
from maasapiserver.v3.constants import V3_API_PREFIX
from maasservicelayer.auth.jwt import UserRole
from maasservicelayer.db.filters import QuerySpec
from maasservicelayer.db.repositories.multiboot import (
    MultiBootDeploymentClauseFactory,
)
from maasservicelayer.exceptions.catalog import NotFoundException
from maasservicelayer.models.auth import AuthenticatedUser
from maasservicelayer.services import ServiceCollectionV3


class MultiBootDeploymentsHandler(Handler):
    """Multi-boot deployment API handler."""

    TAGS = ["MultiBoot"]

    @handler(
        path="/machines/{node_id}/multiboot",
        methods=["GET"],
        tags=TAGS,
        responses={
            200: {"model": MultiBootDeploymentResponse},
            401: {"model": UnauthorizedBodyResponse},
        },
        response_model_exclude_none=True,
        status_code=200,
        dependencies=[
            Depends(check_permissions(required_roles={UserRole.USER}))
        ],
    )
    async def get_layout(
        self,
        node_id: int,
        response: Response,
        authenticated_user: AuthenticatedUser | None = Depends(  # noqa: B008
            get_authenticated_user
        ),
        services: ServiceCollectionV3 = Depends(services),  # noqa: B008
    ) -> MultiBootDeploymentResponse:
        assert authenticated_user is not None
        deployment, os_entries, _ = await services.multiboot_deployments.get_layout(
            node_id
        )
        if not deployment:
            raise NotFoundException()

        response.headers["ETag"] = deployment.etag()

        return MultiBootDeploymentResponse.from_model(
            deployment,
            os_entries,
            self_base_hyperlink=f"{V3_API_PREFIX}/machines/{node_id}/multiboot",
        )

    @handler(
        path="/machines/{node_id}/multiboot",
        methods=["PUT"],
        tags=TAGS,
        responses={
            200: {"model": MultiBootDeploymentResponse},
            201: {"model": MultiBootDeploymentResponse},
            401: {"model": UnauthorizedBodyResponse},
            409: {"model": ConflictBodyResponse},
        },
        response_model_exclude_none=True,
        status_code=200,
        dependencies=[
            Depends(check_permissions(required_roles={UserRole.ADMIN}))
        ],
    )
    async def set_layout(
        self,
        node_id: int,
        request: SetLayoutRequest,
        response: Response,
        authenticated_user: AuthenticatedUser | None = Depends(  # noqa: B008
            get_authenticated_user
        ),
        services: ServiceCollectionV3 = Depends(services),  # noqa: B008
    ) -> MultiBootDeploymentResponse:
        assert authenticated_user is not None

        # Delete existing layout if any
        await services.multiboot_deployments.delete_layout(node_id)

        # Create new layout
        deployment = await services.multiboot_deployments.store_layout(
            node_id=node_id,
            default_os_index=request.default_os_index,
            boot_timeout=request.boot_timeout,
            oses_data=[os_entry.model_dump() for os_entry in request.oses],
        )

        # Fetch the full nested structure for the response
        deployment, os_entries, _ = await services.multiboot_deployments.get_layout(
            node_id
        )

        response.headers["ETag"] = deployment.etag()
        response.status_code = status.HTTP_201_CREATED

        return MultiBootDeploymentResponse.from_model(
            deployment,
            os_entries,
            self_base_hyperlink=f"{V3_API_PREFIX}/machines/{node_id}/multiboot",
        )

    @handler(
        path="/machines/{node_id}/multiboot",
        methods=["DELETE"],
        tags=TAGS,
        responses={
            204: {},
            401: {"model": UnauthorizedBodyResponse},
            412: {"model": PreconditionFailedBodyResponse},
        },
        response_model_exclude_none=True,
        status_code=204,
        dependencies=[
            Depends(check_permissions(required_roles={UserRole.ADMIN}))
        ],
    )
    async def delete_layout(
        self,
        node_id: int,
        etag_if_match: Union[str, None] = Header(
            alias="if-match", default=None
        ),
        authenticated_user: AuthenticatedUser | None = Depends(  # noqa: B008
            get_authenticated_user
        ),
        services: ServiceCollectionV3 = Depends(services),  # noqa: B008
    ) -> Response:
        assert authenticated_user is not None

        # TODO: add etag check before deleting
        await services.multiboot_deployments.delete_layout(node_id)

        return Response(status_code=status.HTTP_204_NO_CONTENT)

