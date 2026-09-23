package com.hmdp.gateway;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.assertj.core.api.Assertions.*;

class GatewayKeyServiceTest {
    private GatewayTestDatabase db;
    private GatewayKeyService keys;

    @BeforeEach void setUp() { db = new GatewayTestDatabase(); keys = new GatewayKeyService(db.jdbc); }

    @Test void plaintextIsOnlyReturnedAtCreationAndDatabaseStoresItsHash() {
        Map<String, Object> created = keys.create(10, "开发环境");
        String secret = (String) created.get("key");
        assertThat(secret).startsWith("mh_").hasSize(46);
        assertThat(keys.authenticate("Bearer " + secret).userId()).isEqualTo(10);
        assertThat(keys.authenticate("bearer " + secret).userId()).isEqualTo(10);
        assertThat(db.jdbc.queryForObject("SELECT key_hash FROM tb_gateway_api_key", String.class)).isEqualTo(GatewayKeyService.hash(secret));
        assertThat(keys.list(10).getFirst()).doesNotContainKeys("key", "keyHash", "key_hash");
        assertThat(keys.list(11)).isEmpty();
    }

    @Test void revocationCannotTargetAnotherUsersKey() {
        Map<String, Object> created = keys.create(10, "key");
        String id = (String) created.get("id");
        String authorization = "Bearer " + created.get("key");
        keys.revoke(11, id);
        assertThat(keys.authenticate(authorization).userId()).isEqualTo(10);
        keys.revoke(10, id);
        assertThatThrownBy(() -> keys.authenticate(authorization)).isInstanceOfSatisfying(GatewayException.class,
                e -> assertThat(e.status()).isEqualTo(401));
        assertThat(keys.list(10).getFirst().get("status")).isEqualTo(0);
    }

    @Test void rejectsInvalidOrMissingCredentials() {
        assertThatThrownBy(() -> keys.authenticate(null)).isInstanceOf(GatewayException.class);
        assertThatThrownBy(() -> keys.authenticate("Bearer upstream-secret")).isInstanceOf(GatewayException.class);
        assertThatThrownBy(() -> keys.authenticate("Bearer mh_invented")).isInstanceOf(GatewayException.class);
    }
}
