import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Role, User


PAGES = [
    ("/", 'data-page="public"', "Campanhas inteligentes"),
    ("/login", 'id="loginForm"', 'name="password"'),
    ("/cadastro", 'id="registerForm"', 'name="accept_terms"'),
    ("/dashboard", 'data-page="dashboard"', 'id="performanceChart"'),
    ("/contatos", 'data-page="contacts"', 'id="contactsTable"'),
    ("/campanhas", 'data-page="campaigns"', 'id="campaignEditorForm"'),
    ("/conteudo-ia", 'data-page="content"', 'id="generatedContent"'),
    ("/integracoes", 'data-page="integrations"', 'id="integrationCards"'),
    ("/historico", 'data-page="history"', 'id="historyTable"'),
    ("/configuracoes", 'data-page="settings"', 'id="settingsForm"'),
    ("/privacidade", 'data-page="public"', "Política de Privacidade"),
    ("/termos", 'data-page="public"', "Termos de Uso"),
]


@pytest.mark.parametrize(("path", "page_marker", "content_marker"), PAGES)
def test_html_pages_render(client, auth, path, page_marker, content_marker):
    response = client.get(path)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert page_marker in response.text
    assert content_marker in response.text
    assert 'id="main-content"' in response.text
    assert 'id="appToast"' in response.text
    assert 'id="confirmModal"' in response.text


@pytest.mark.parametrize(
    ("path", "contracts"),
    [
        ("/login", ['id="loginForm"', 'name="email"', 'name="password"', 'id="forgotPassword"']),
        ("/cadastro", ['id="registerForm"', 'name="company_name"', 'name="password_confirmation"', 'name="accept_terms"']),
        ("/contatos", ['id="contactForm"', 'name="phone"', 'name="source"', 'id="listForm"', 'id="csvFile"']),
        ("/campanhas", ['id="campaignEditorForm"', 'name="campaign_id"', 'name="contact_list_id"', 'name="scheduled_at"', 'name="media"']),
        ("/conteudo-ia", ['id="contentForm"', 'name="product"', 'name="audience"', 'name="required_information"']),
        ("/integracoes", ['id="integrationForm"', 'name="provider"', 'name="external_account_id"', 'name="token"']),
        ("/configuracoes", ['id="settingsForm"', 'name="daily_limit"', 'id="passwordForm"', 'name="new_password"']),
    ],
)
def test_javascript_dom_contracts_are_preserved(client, auth, path, contracts):
    html = client.get(path).text

    for contract in contracts:
        assert contract in html


@pytest.mark.parametrize(
    "path",
    ["/dashboard", "/contatos", "/campanhas", "/conteudo-ia", "/integracoes", "/historico", "/configuracoes", "/administracao"],
)
def test_private_pages_redirect_anonymous_users(client, path):
    response = client.get(path, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_regular_user_cannot_render_administration(auth):
    response = auth["client"].get("/administracao", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/dashboard"


def test_admin_can_render_administration(auth):
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == "ana@example.com"))
        user.role = Role.admin
        db.commit()

    response = auth["client"].get("/administracao")

    assert response.status_code == 200
    assert 'data-page="admin"' in response.text
    assert 'id="adminOverview"' in response.text


@pytest.mark.parametrize(
    "asset",
    [
        "/static/css/variables.css",
        "/static/css/base.css",
        "/static/css/layout.css",
        "/static/css/components.css",
        "/static/css/forms.css",
        "/static/css/tables.css",
        "/static/css/animations.css",
        "/static/css/dashboard.css",
        "/static/css/pages.css",
        "/static/css/responsive.css",
        "/static/js/navigation.js",
        "/static/js/animations.js",
        "/static/js/init.js",
        "/static/js/app.js",
        "/static/images/favicon.svg",
    ],
)
def test_frontend_assets_are_available(client, asset):
    response = client.get(asset)

    assert response.status_code == 200
    assert response.content
