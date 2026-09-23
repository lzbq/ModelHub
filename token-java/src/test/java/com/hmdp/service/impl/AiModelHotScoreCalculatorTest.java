package com.hmdp.service.impl;

import com.hmdp.config.AiModelHotScoreProperties;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class AiModelHotScoreCalculatorTest {

    private AiModelHotScoreCalculator calculator;

    @BeforeEach
    void setUp() {
        calculator = new AiModelHotScoreCalculator(new AiModelHotScoreProperties());
    }

    @Test
    void noActivityShouldProduceZeroScore() {
        long score = calculator.calculate(
                AiModelHotScoreCalculator.Signals.ZERO,
                AiModelHotScoreCalculator.Signals.ZERO);

        assertThat(score).isZero();
    }

    @Test
    void moreRecentBusinessActivityShouldIncreaseScore() {
        long lowScore = calculator.calculate(
                new AiModelHotScoreCalculator.Signals(100D, 1D),
                AiModelHotScoreCalculator.Signals.ZERO);
        long highScore = calculator.calculate(
                new AiModelHotScoreCalculator.Signals(3_000D, 50D),
                AiModelHotScoreCalculator.Signals.ZERO);

        assertThat(highScore).isGreaterThan(lowScore);
        assertThat(highScore).isBetween(0L, 10_000L);
    }

    @Test
    void positiveGrowthShouldScoreHigherThanDeclineForSameRecentActivity() {
        AiModelHotScoreCalculator.Signals recent =
                new AiModelHotScoreCalculator.Signals(2_000D, 40D);

        long growing = calculator.calculate(
                recent, new AiModelHotScoreCalculator.Signals(500D, 10D));
        long declining = calculator.calculate(
                recent, new AiModelHotScoreCalculator.Signals(4_000D, 80D));

        assertThat(growing).isGreaterThan(declining);
    }

    @Test
    void saturatedViewsAndPurchasesShouldReachMaxScoreWithoutCallMetric() {
        long score = calculator.calculate(
                new AiModelHotScoreCalculator.Signals(5_000D, 100D),
                AiModelHotScoreCalculator.Signals.ZERO);

        assertThat(score).isEqualTo(10_000L);
    }

    @Test
    void timeDecayShouldFollowConfiguredHalfLife() {
        assertThat(calculator.decayFactor(0D)).isEqualTo(1D);
        assertThat(calculator.decayFactor(12D)).isEqualTo(0.5D);
        assertThat(calculator.decayFactor(24D)).isEqualTo(0.25D);
    }
}
