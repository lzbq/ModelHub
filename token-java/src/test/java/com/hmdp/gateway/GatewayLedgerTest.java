package com.hmdp.gateway;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;

import static com.hmdp.gateway.GatewayTypes.*;
import static org.assertj.core.api.Assertions.*;

class GatewayLedgerTest {
    private GatewayTestDatabase db;
    private GatewayLedger ledger;
    private GatewayProperties properties;
    private final Identity identity = new Identity(10, "key:first", "first");
    private final Model model = new Model("test", 1, "Test", "Provider", "actual-test", 100, 400, 128000);
    private final String fingerprint = "a".repeat(64);

    @BeforeEach void setUp() {
        db = new GatewayTestDatabase();
        properties = new GatewayProperties();
        ledger = new GatewayLedger(db.jdbc, db.manager, properties);
    }

    private Entry reserve(String key, long amount) { return ledger.reserve(identity, key, fingerprint, model, amount).entry(); }

    @Test void settlementPreservesOtherRequestsReservationsAndIsIdempotent() {
        Entry a = reserve("a", 1000);
        reserve("b", 500);
        assertThat(ledger.settle(a.requestId(), new Usage(80, 20), "{}" )).isTrue();
        assertThat(ledger.settle(a.requestId(), new Usage(80, 20), "{}" )).isTrue();
        assertThat(db.value("used_quota")).isEqualTo(100);
        assertThat(db.value("reserved_quota")).isEqualTo(500);
        assertThat(db.jdbc.queryForObject("SELECT cost_yuan FROM tb_gateway_usage WHERE request_id=?", java.math.BigDecimal.class, a.requestId()))
                .isEqualByComparingTo("0.00016");
        ledger.release(a.requestId(), "late_error");
        assertThat(db.value("reserved_quota")).isEqualTo(500);
    }

    @Test void insufficientQuotaRollsBackTheRequestInsertion() {
        assertThatThrownBy(() -> reserve("large", 10001)).isInstanceOf(GatewayException.class);
        assertThat(db.value("reserved_quota")).isZero();
        assertThat(ledger.find(identity.principal(), "large")).isNull();
    }

    @Test void expiredAccountsCannotReserve() {
        db.jdbc.update("UPDATE tb_token_account SET expire_time = '2000-01-01 00:00:00'");
        assertThatThrownBy(() -> reserve("expired", 10)).isInstanceOf(GatewayException.class);
    }

    @Test void repeatedKeyReturnsOriginalAndDifferentPayloadConflicts() {
        Entry original = reserve("idempotent", 500);
        Reservation repeat = ledger.reserve(identity, "idempotent", fingerprint, model, 500);
        assertThat(repeat.fresh()).isFalse();
        assertThat(repeat.entry().requestId()).isEqualTo(original.requestId());
        assertThat(db.value("reserved_quota")).isEqualTo(500);
        assertThatThrownBy(() -> ledger.reserve(identity, "idempotent", "b".repeat(64), model, 500))
                .isInstanceOfSatisfying(GatewayException.class, e -> assertThat(e.status()).isEqualTo(409));
    }

    @Test void concurrentApiKeysCannotOverReserveOneAccount() throws Exception {
        db.jdbc.update("UPDATE tb_token_account SET total_quota=1000");
        CountDownLatch start = new CountDownLatch(1);
        try (var workers = Executors.newFixedThreadPool(2)) {
            List<Future<Boolean>> futures = List.of(1, 2).stream().map(i -> workers.submit(() -> {
                start.await();
                try {
                    ledger.reserve(new Identity(10, "key:" + i, String.valueOf(i)), "request", fingerprint, model, 700);
                    return true;
                } catch (GatewayException e) { assertThat(e.status()).isEqualTo(402); return false; }
            })).toList();
            start.countDown();
            int accepted = 0;
            for (Future<Boolean> future : futures) if (future.get()) accepted++;
            assertThat(accepted).isEqualTo(1);
        }
        assertThat(db.value("reserved_quota")).isEqualTo(700);
        assertThat(db.jdbc.queryForObject("SELECT COUNT(*) FROM tb_gateway_usage", Long.class)).isEqualTo(1);
    }

    @Test void concurrentSameIdempotencyKeyOnlyReservesOnce() throws Exception {
        CountDownLatch start = new CountDownLatch(1);
        try (var workers = Executors.newFixedThreadPool(2)) {
            Future<Reservation> a = workers.submit(() -> { start.await(); return ledger.reserve(identity, "same", fingerprint, model, 600); });
            Future<Reservation> b = workers.submit(() -> { start.await(); return ledger.reserve(identity, "same", fingerprint, model, 600); });
            start.countDown();
            assertThat(a.get().entry().requestId()).isEqualTo(b.get().entry().requestId());
            assertThat(a.get().fresh()).isNotEqualTo(b.get().fresh());
        }
        assertThat(db.value("reserved_quota")).isEqualTo(600);
    }

    @Test void actualUsageCanExceedEstimateWhenBalanceAllows() {
        Entry entry = reserve("underestimate", 100);
        assertThat(ledger.settle(entry.requestId(), new Usage(200, 100), "{}")).isTrue();
        assertThat(db.value("used_quota")).isEqualTo(300);
        assertThat(db.value("reserved_quota")).isZero();
    }

    @Test void insufficientSettlementKeepsReservationAndTrueUsageForReconciliation() {
        db.jdbc.update("UPDATE tb_token_account SET total_quota=300");
        Entry a = reserve("a", 100);
        reserve("b", 150);
        assertThat(ledger.settle(a.requestId(), new Usage(150, 100), "{}")).isFalse();
        assertThat(db.value("used_quota")).isZero();
        assertThat(db.value("reserved_quota")).isEqualTo(250);
        assertThat(ledger.find(identity.principal(), "a").status()).isEqualTo("NEEDS_RECONCILIATION");
        assertThat(db.jdbc.queryForObject("SELECT total_tokens FROM tb_gateway_usage WHERE request_id=?", Long.class, a.requestId())).isEqualTo(250);
    }

    @Test void confirmedRejectionReleasesExactlyOnce() {
        Entry entry = reserve("reject", 1000);
        ledger.release(entry.requestId(), "upstream_rejected_400");
        ledger.release(entry.requestId(), "duplicate");
        assertThat(db.value("reserved_quota")).isZero();
        assertThat(db.value("used_quota")).isZero();
        assertThat(ledger.find(identity.principal(), "reject").status()).isEqualTo("FAILED");
    }

    @Test void transportUncertaintyAndStaleProcessKeepReservations() {
        Entry uncertain = reserve("timeout", 500);
        ledger.uncertain(uncertain.requestId(), "timeout");
        ledger.release(uncertain.requestId(), "late_failure");
        reserve("crash", 300);
        db.jdbc.update("UPDATE tb_gateway_usage SET created_at='2000-01-01 00:00:00'");
        properties.setEnabled(true);
        ledger.markInterruptedRequests();
        assertThat(db.value("reserved_quota")).isEqualTo(800);
        assertThat(ledger.find(identity.principal(), "crash").status()).isEqualTo("NEEDS_RECONCILIATION");
    }

    @Test void usageHistoryIsScopedToTheCurrentUser() {
        reserve("mine", 100);
        assertThat(ledger.usage(10, 1).getTotal()).isEqualTo(1);
        assertThat(ledger.usage(11, 1).getTotal()).isZero();
    }
}
