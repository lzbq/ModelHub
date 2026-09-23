package com.hmdp.service.impl;

import static org.mockito.Mockito.RETURNS_DEFAULTS;
import static org.mockito.Mockito.mock;

/** MyBatis chain methods erase their return type to Object, which RETURNS_SELF excludes. */
final class FluentChainMocks {
    private FluentChainMocks() { }

    static <T> T chainMock(Class<T> type) {
        return mock(type, invocation -> switch (invocation.getMethod().getName()) {
            case "eq", "le", "gt", "set", "setSql", "orderByAsc", "orderByDesc", "last" -> invocation.getMock();
            default -> RETURNS_DEFAULTS.answer(invocation);
        });
    }
}
