"""Create/verify the managed PharmStock Kafka topics."""

from pharmstock.streaming import MANAGED_TOPICS, KafkaAdmin, KafkaSettings


def main() -> None:
    settings = KafkaSettings.from_env()
    admin = KafkaAdmin(settings)
    print("=== PharmStock V2 / Stage 3A Kafka Topics ===")
    print(f"Bootstrap server: {settings.bootstrap_servers}")
    print("Waiting for broker...")
    admin.wait_until_available()
    admin.ensure_topics()
    partitions = admin.topic_partitions()
    for spec in MANAGED_TOPICS:
        print(
            f"  {spec.name:<30} partitions={partitions.get(spec.name, 0)} "
            f"replication(local)={spec.replication_factor}"
        )
    print("\nSTAGE_3A_TOPICS_STATUS=PASS")


if __name__ == "__main__":
    main()
