"""``http/SchemaRepresentation.test.ts``."""

from pyfect.http import schema as HS
from pyfect.schema import representation as R
from pyfect.schema.representation._code_document import code_document


def test_generates_code_for_declaration_schemas() -> None:
    """HTTP schema representations / generates code for declaration schemas"""
    document = R.to_representations((HS.Headers, HS.Cookies, HS.Cookie, HS.UrlParams))
    assert [
        node.representation for node in document.representations if isinstance(node, R.Declaration)
    ] == [
        R.RepresentationAnnotation("effect/http/Headers"),
        R.RepresentationAnnotation("effect/http/Cookies"),
        R.RepresentationAnnotation("effect/http/Cookie"),
        R.RepresentationAnnotation("effect/http/UrlParams"),
    ]
    output = code_document(document)
    assert output.codes == (
        R.Code('HS.Headers.annotate(expected="Headers")', "headers.Headers"),
        R.Code('HS.Cookies.annotate(expected="Cookies")', "cookies.Cookies"),
        R.Code('HS.Cookie.annotate(expected="Cookie")', "cookies.Cookie"),
        R.Code('HS.UrlParams.annotate(expected="UrlParams")', "url_params.UrlParams"),
    )
    assert output.artifacts == (
        R.ImportArtifact("from pyfect.http import schema as HS"),
        R.ImportArtifact("from pyfect.http import headers"),
        R.ImportArtifact("from pyfect.http import cookies"),
        R.ImportArtifact("from pyfect.http import url_params"),
    )
    namespace: dict[str, object] = {"__name__": "generated"}
    exec(R.to_code_module(output), namespace)
    assert namespace["Schema0"] is not None
