"""仅包含 Team、成员映射与系统设置的数据模型。"""
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils.time_utils import get_now


class Team(Base):
    __tablename__ = "teams"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), nullable=False)
    access_token_encrypted = Column(Text, nullable=False)
    id_token_encrypted = Column(Text)
    refresh_token_encrypted = Column(Text)
    session_token_encrypted = Column(Text)
    client_id = Column(String(100))
    encryption_key_id = Column(String(50))
    account_id = Column(String(100))
    team_name = Column(String(255))
    plan_type = Column(String(50))
    subscription_plan = Column(String(100))
    expires_at = Column(DateTime)
    current_members = Column(Integer, default=0)
    max_members = Column(Integer, default=6)
    status = Column(String(20), default="active")
    account_role = Column(String(50))
    device_code_auth_enabled = Column(Boolean, default=False)
    error_count = Column(Integer, default=0)
    last_sync = Column(DateTime)
    created_at = Column(DateTime, default=get_now)
    # 保留该列只为兼容现有数据库；成员管理版始终使用 normal。
    pool_type = Column(String(20), default="normal")

    team_accounts = relationship("TeamAccount", back_populates="team", cascade="all, delete-orphan")
    email_mappings = relationship("TeamEmailMapping", back_populates="team", cascade="all, delete-orphan")

    __table_args__ = (Index("idx_status", "status"),)


class TeamAccount(Base):
    __tablename__ = "team_accounts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    team_id = Column(Integer, ForeignKey("teams.id", ondelete="CASCADE"), nullable=False)
    account_id = Column(String(100), nullable=False)
    account_name = Column(String(255))
    is_primary = Column(Boolean, default=False)
    created_at = Column(DateTime, default=get_now)

    team = relationship("Team", back_populates="team_accounts")
    __table_args__ = (Index("idx_team_account", "team_id", "account_id", unique=True),)


class TeamEmailMapping(Base):
    __tablename__ = "team_email_mappings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    team_id = Column(Integer, ForeignKey("teams.id", ondelete="CASCADE"), nullable=False)
    email = Column(String(255), nullable=False)
    status = Column(String(20), default="invited", nullable=False)
    source = Column(String(20), default="sync", nullable=False)
    last_seen_at = Column(DateTime, default=get_now)
    missing_sync_count = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=get_now)
    updated_at = Column(DateTime, default=get_now, onupdate=get_now)

    team = relationship("Team", back_populates="email_mappings")
    __table_args__ = (
        Index("idx_team_email_unique", "team_id", "email", unique=True),
        Index("idx_team_email_email", "email"),
        Index("idx_team_email_status", "team_id", "status"),
    )


class Setting(Base):
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(100), unique=True, nullable=False)
    value = Column(Text)
    description = Column(String(255))
    created_at = Column(DateTime, default=get_now)
    updated_at = Column(DateTime, default=get_now, onupdate=get_now)

    __table_args__ = (Index("idx_key", "key"),)
