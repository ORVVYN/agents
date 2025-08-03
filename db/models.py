from sqlalchemy import Column, Integer, String, Text, Float, ForeignKey, DateTime
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime

Base = declarative_base()

class Supplier(Base):
    __tablename__ = "suppliers"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    category = Column(String, nullable=False)
    address = Column(String)
    phone = Column(String)
    email = Column(String)
    website = Column(String)
    whatsapp = Column(String)
    city = Column(String)
    source_query = Column(String)  # original user search term
    created_at = Column(DateTime, default=datetime.utcnow)

class Requester(Base):
    __tablename__ = "requesters"

    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, nullable=False, unique=True)
    username = Column(String)
    full_name = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

class Buyer(Base):
    __tablename__ = "buyers"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)  # company name
    contact_person = Column(String)
    phone = Column(String)
    email = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)


class Application(Base):
    __tablename__ = "applications"

    id = Column(Integer, primary_key=True)
    requester_id = Column(Integer, ForeignKey("requesters.id"))
    buyer_id = Column(Integer, ForeignKey("buyers.id"))
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=True)
    amocrm_id = Column(Integer)  # synced lead id
    search_term = Column(String)
    status = Column(String, default="new")  # new / manager_review / negotiating / closed
    details = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    requester = relationship("Requester")
    buyer = relationship("Buyer")
    supplier = relationship("Supplier")

class ManagerAction(Base):
    __tablename__ = "manager_actions"

    id = Column(Integer, primary_key=True)
    application_id = Column(Integer, ForeignKey("applications.id"))
    action = Column(String)  # approve_negotiation / request_info / reject
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    application = relationship("Application")

class EmailRecord(Base):
    __tablename__ = "emails"

    id = Column(Integer, primary_key=True)
    application_id = Column(Integer, ForeignKey("applications.id"))
    to_address = Column(String)
    subject = Column(String)
    body = Column(Text)
    direction = Column(String, default="out")  # out / in
    sent_at = Column(DateTime, default=datetime.utcnow)

class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"))
    amount = Column(Float)
    currency = Column(String, default="RUB")
    pdf_path = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

    supplier = relationship("Supplier")
