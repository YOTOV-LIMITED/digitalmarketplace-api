from __future__ import absolute_import

import os
from datetime import datetime
from itertools import product

import mock
import pytest
from alembic.command import upgrade
from alembic.config import Config
from flask.ext.migrate import Migrate, MigrateCommand
from flask.ext.script import Manager
from six import iteritems, iterkeys
from sqlalchemy import inspect

from app import create_app
from app.models import (
    db, Framework, SupplierFramework, Supplier, User, ContactInformation, DraftService, Lot, Service, FrameworkLot
)


@pytest.fixture(autouse=True, scope='session')
def db_migration(request):
    print("Doing db setup")
    app = create_app('test')
    Migrate(app, db)
    Manager(db, MigrateCommand)
    ALEMBIC_CONFIG = \
        os.path.join(os.path.dirname(__file__),
                     '../migrations/alembic.ini')
    config = Config(ALEMBIC_CONFIG)
    config.set_main_option(
        "script_location",
        "migrations")
    with app.app_context():
        upgrade(config, 'head')
    print("Done db setup")

    def teardown():
        app = create_app('test')
        with app.app_context():
            db.session.remove()
            db.engine.execute("drop sequence suppliers_supplier_id_seq cascade")
            db.drop_all()
            db.engine.execute("drop table alembic_version")
            insp = inspect(db.engine)
            for enum in insp.get_enums():
                db.Enum(name=enum['name']).drop(db.engine)
            db.get_engine(app).dispose()
    request.addfinalizer(teardown)


@pytest.fixture(scope='session')
def app(request):
    return create_app('test')


@pytest.fixture(params=[{}])
def draft_service(request, app, supplier_framework):
    with app.app_context():
        supplier_id = Supplier.query.filter(Supplier.supplier_id == supplier_framework['supplierId']).first()
        framework = Framework.query.filter(Framework.slug == supplier_framework['frameworkSlug']).first()
        lot = Lot.query.filter(Lot.slug == 'digital-specialists').first()
        fl_query = {
            'framework_id': framework.id,
            'lot_id': lot.id
        }
        fl = FrameworkLot(**fl_query)

        ds = DraftService(
            framework=framework,
            lot=lot,
            service_id="1234567890",
            supplier=supplier_id,
            data={},
            status='submitted',
            updated_at=datetime.now(),
            created_at=datetime.now()
        )
        db.session.add(fl)
        db.session.add(ds)
        db.session.commit()

        def teardown():
            with app.app_context():
                FrameworkLot.query.filter(
                    *[getattr(FrameworkLot, k) == v for k, v in fl_query.items()]
                ).delete(synchronize_session=False)
                Service.query.filter(Service.service_id == ds.service_id).delete(synchronize_session=False)
                DraftService.query.filter(DraftService.service_id == ds.service_id).delete(synchronize_session=False)
                db.session.commit()

        request.addfinalizer(teardown)

        with mock.patch('app.models.url_for', autospec=lambda i, **values: 'test.url/test'):
            Service.create_from_draft(ds, 'enabled')
            return ds.serialize()


@pytest.fixture(params=[{'supplier_id': None}])
def supplier(request, app):
    with app.app_context():
        s = Supplier(
            supplier_id=request.param['supplier_id'],
            name=u"Supplier name",
            description="",
            clients=[]
        )
        db.session.add(s)
        db.session.commit()

        return {'id': s.supplier_id}


@pytest.fixture(params=[{'on_framework': True}])
def supplier_framework(request, app, supplier, live_example_framework):
    with app.app_context():
        sf = SupplierFramework(
            supplier_id=supplier['id'],
            framework_id=live_example_framework['id'],
            **request.param
        )
        db.session.add(sf)
        db.session.commit()

        return sf.serialize()


_framework_kwargs_whitelist = set(("status", "framework", "framework_agreement_details",))


def _update_framework(request, app, slug, **kwargs):
    if not kwargs:
        # request doesn't really care about any more specific properties of the Framework. nothing for us
        # to do.
        return

    # first whitelist the kwargs to limit what we have to worry about
    kwargs = {k: v for k, v in iteritems(kwargs) if k in _framework_kwargs_whitelist}

    framework = Framework.query.filter(
        Framework.slug == slug
    ).first()
    original_values = {k: getattr(framework, k) for k in iterkeys(kwargs)}
    for k, v in iteritems(kwargs):
        setattr(framework, k, v)

    db.session.add(framework)
    db.session.commit()

    def teardown():
        with app.app_context():
            framework = Framework.query.filter(
                Framework.slug == slug
            ).first()
            for k, v in iteritems(original_values):
                setattr(framework, k, v)

            db.session.add(framework)
            db.session.commit()

    request.addfinalizer(teardown)
    return framework.serialize()


def _add_framework(request, app, slug, **kwargs):
    # first whitelist the kwargs to limit what we have to worry about
    kwargs = {k: v for k, v in iteritems(kwargs) if k in _framework_kwargs_whitelist}
    if "status" in kwargs and "clarification_questions_open" not in kwargs:
        kwargs["clarification_questions_open"] = (kwargs["status"] == "open")

    framework = Framework(slug=slug, name=slug, **kwargs)
    db.session.add(framework)
    db.session.commit()

    def teardown():
        with app.app_context():
            Framework.query.filter(Framework.slug == slug).delete()
            db.session.commit()

    request.addfinalizer(teardown)
    return framework.serialize()


def _framework_fixture_inner(request, app, slug, **kwargs):
    with app.app_context():
        # we have to do a switch between two implementations here as in some cases a matching Framework
        # may already be in the database (e.g. Frameworks that were inserted by migrations)
        inner_func = (
            _update_framework if Framework.query.filter(Framework.slug == slug).first() else _add_framework
        )
        return inner_func(request, app, slug, **kwargs)


_generic_framework_agreement_details = {"frameworkAgreementVersion": "v1.0"}

_g8_framework_defaults = {
    "slug": "g-cloud-8",
    "framework": "g-cloud",
    "framework_agreement_details": _generic_framework_agreement_details,
}
_g7_framework_defaults = {
    "slug": "g-cloud-7",
    "framework": "g-cloud",
    "framework_agreement_details": None,
}
_g6_framework_defaults = {
    "slug": "g-cloud-6",
    "framework": "g-cloud",
    "framework_agreement_details": None,
}
_dos_framework_defaults = {
    "slug": "digital-outcomes-and-specialists",
    "framework": "dos",
    "framework_agreement_details": None,
}
_example_framework_details = {
    "slug": "example-framework",
    "framework": "g-cloud",
    "framework_agreement_details": None
}


def _supplierframework_fixture_inner(request, app, sf_kwargs=None):
    sf_kwargs = sf_kwargs or {}
    supplier_framework_id_pairs = set()
    with app.app_context():
        for framework, supplier in product(Framework.query.all(), Supplier.query.all()):
            supplier_framework = SupplierFramework(
                supplier=supplier,
                framework=framework,
                **sf_kwargs
            )
            supplier_framework_id_pairs.add((supplier.supplier_id, framework.id,))
            db.session.add(supplier_framework)

        db.session.commit()

    def teardown():
        with app.app_context():
            for supplier_id, framework_id in supplier_framework_id_pairs:
                SupplierFramework.query.filter(
                    SupplierFramework.supplier_id == supplier_id,
                    SupplierFramework.framework_id == framework_id,
                ).delete()
            db.session.commit()

    request.addfinalizer(teardown)


def _supplier_fixture_inner(request, app, supplier_kwargs=None, ci_kwargs=None):
    supplier_kwargs = supplier_kwargs or {}
    supplier_kwargs = dict({
        "name": "Supplier {}".format(supplier_kwargs.get("supplier_id", "")),
        "description": "some description",
    }, **supplier_kwargs)

    with app.app_context():
        supplier = Supplier(**supplier_kwargs)
        db.session.add(supplier)
        db.session.flush()

        ci_kwargs = ci_kwargs or {}
        ci_kwargs = dict({
            "contact_name": "Contact for supplier {}".format(supplier.supplier_id),
            "email": "{}@contact.com".format(supplier.supplier_id),
            "postcode": "SW1A 1AA",
            "supplier_id": supplier.supplier_id,
        }, **ci_kwargs)

        contact_information = ContactInformation(**ci_kwargs)
        db.session.add(contact_information)

        db.session.commit()

        supplier_id = supplier.supplier_id
        contact_information_id = contact_information.id

    def teardown():
        with app.app_context():
            ContactInformation.query.filter(ContactInformation.id == contact_information_id).delete()
            Supplier.query.filter(Supplier.supplier_id == supplier_id).delete()
            db.session.commit()

    request.addfinalizer(teardown)
    return supplier_id


def _user_fixture_inner(request, app, user_kwargs=None):
    user_kwargs = user_kwargs or {}
    user_kwargs = dict({
        "email_address": "test+{}@digital.gov.uk".format(user_kwargs.get("id", "replaceme")),
        "active": True,
        "password": "fake password",
        "password_changed_at": datetime.now(),
        "name": "my name",
    }, **user_kwargs)

    with app.app_context():
        user = User(**user_kwargs)
        db.session.add(user)
        db.session.commit()

        # if we didn't know the user id at insert time and didn't have an email we should replace it now
        # so we don't end up with collisions
        if user.email_address == "test+replaceme@digital.gov.uk":
            user.email_address = "test+{}@digital.gov.uk".format(user.id)
            db.session.add(user)
            db.session.commit()

        user_id = user.id

    def teardown():
        with app.app_context():
            User.query.filter(User.id == user_id).delete()
            db.session.commit()

    request.addfinalizer(teardown)
    return user_id


# Frameworks


@pytest.fixture()
def open_example_framework(request, app):
    return _framework_fixture_inner(request, app, **dict(_example_framework_details, status="open"))


@pytest.fixture(params=[{}])
def live_example_framework(request, app):
    return _framework_fixture_inner(request, app, **dict(_example_framework_details, status="live", **request.param))


@pytest.fixture()
def open_g8_framework(request, app):
    return _framework_fixture_inner(request, app, **dict(_g8_framework_defaults, status="open"))


@pytest.fixture()
def live_g8_framework(request, app):
    return _framework_fixture_inner(request, app, **dict(_g8_framework_defaults, status="live"))


@pytest.fixture()
def live_g8_framework_2_variations(request, app):
    _framework_fixture_inner(request, app, **dict(
        _g8_framework_defaults,
        status="live",
        framework_agreement_details=dict(_generic_framework_agreement_details, variations={
            "banana": {
                "createdAt": "2016-06-06T20:01:34.000000Z",
            },
            "toblerone": {
                "createdAt": "2016-07-06T21:09:09.000000Z",
            },
        }),
    ))


@pytest.fixture()
def open_g6_framework(request, app):
    return _framework_fixture_inner(request, app, **dict(_g6_framework_defaults, status="open"))


@pytest.fixture()
def expired_g6_framework(request, app):
    return _framework_fixture_inner(request, app, **dict(_g6_framework_defaults, status="expired"))


@pytest.fixture()
def open_dos_framework(request, app):
    return _framework_fixture_inner(request, app, **dict(_dos_framework_defaults, status="open"))


@pytest.fixture()
def live_dos_framework(request, app):
    return _framework_fixture_inner(request, app, **dict(_dos_framework_defaults, status="live"))


@pytest.fixture()
def expired_dos_framework(request, app):
    return _framework_fixture_inner(request, app, **dict(_dos_framework_defaults, status="expired"))


# Suppliers


@pytest.fixture()
def supplier_basic(request, app):
    return _supplier_fixture_inner(request, app, supplier_kwargs={"supplier_id": 1})


@pytest.fixture()
def supplier_basic_alt(request, app):
    return _supplier_fixture_inner(request, app, supplier_kwargs={"supplier_id": 2})


# Users


@pytest.fixture()
def user_role_supplier(request, app, supplier_basic):
    return _user_fixture_inner(request, app, user_kwargs={
        "id": 1,
        "role": "supplier",
        "supplier_id": supplier_basic,
    })


@pytest.fixture()
def user_role_supplier_alt(request, app, supplier_basic_alt):
    return _user_fixture_inner(request, app, user_kwargs={
        "id": 2,
        "role": "supplier",
        "supplier_id": supplier_basic_alt,
    })


# Frameworks & Suppliers with some SupplierFrameworks setup


@pytest.fixture()
def live_g8_framework_2_variations_suppliers_not_on_framework(
        request,
        app,
        live_g8_framework_2_variations,
        user_role_supplier,
):
    _supplierframework_fixture_inner(request, app)


@pytest.fixture()
def live_g8_framework_2_variations_suppliers_on_framework(
        request,
        app,
        live_g8_framework_2_variations,
        user_role_supplier,
):
    _supplierframework_fixture_inner(request, app, sf_kwargs={"on_framework": True})


@pytest.fixture()
def live_g8_framework_2_variations_suppliers_on_framework_with_alt(
        request,
        app,
        live_g8_framework_2_variations,
        user_role_supplier,
        user_role_supplier_alt,
):
    _supplierframework_fixture_inner(request, app, sf_kwargs={"on_framework": True})


@pytest.fixture()
def live_g8_framework_suppliers_on_framework(
        request,
        app,
        live_g8_framework,
        user_role_supplier,
):
    _supplierframework_fixture_inner(request, app, sf_kwargs={"on_framework": True})
