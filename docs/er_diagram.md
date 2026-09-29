# Source data model

```mermaid
erDiagram
    COUNTRY_REFERENCE {
        int CountryCode PK
        string Country
    }

    DEMOGRAPHICS {
        int UserID PK
        date DateOfBirth
        string Gender
        int CountryCode FK
    }

    GAMES {
        int UserID FK
        date Date
        int CashGames
        float Odds
        decimal Wagers
        decimal Winnings
    }

    TOURNAMENTS {
        int UserID FK
        date Date
        int Tournaments
        float Odds
        decimal Wagers
        decimal Winnings
    }

    DEPOSITS_SUCCESSFUL {
        int UserID FK
        bigint DepositID PK
        date Date
        time Time
        string PayMeth
        string PayMethCat
        decimal Amount
        string Status
    }

    DEPOSITS_FAILED {
        int UserID FK
        bigint DepositID PK
        date Date
        time Time
        string PayMeth
        string PayMethCat
        decimal Amount
        string Status
    }

    WITHDRAWALS_SUCCESSFUL {
        int UserID FK
        bigint WithdrawalID PK
        date Date
        time Time
        string PayMeth
        string PayMethCat
        decimal Amount
        string Status
    }

    WITHDRAWALS_FAILED {
        int UserID FK
        bigint WithdrawalID PK
        date Date
        time Time
        string PayMeth
        string PayMethCat
        decimal Amount
        string Status
    }

    COUNTRY_REFERENCE ||--o{ DEMOGRAPHICS : maps
    DEMOGRAPHICS ||--o{ GAMES : has
    DEMOGRAPHICS ||--o{ TOURNAMENTS : has
    DEMOGRAPHICS ||--o{ DEPOSITS_SUCCESSFUL : makes
    DEMOGRAPHICS ||--o{ DEPOSITS_FAILED : makes
    DEMOGRAPHICS ||--o{ WITHDRAWALS_SUCCESSFUL : makes
    DEMOGRAPHICS ||--o{ WITHDRAWALS_FAILED : makes
```

## Relationship notes

- `CountryReference.CountryCode` is the lookup key for `Demographics.CountryCode`.
- `Demographics.UserID` is the main entity key for user-level analysis.
- `Games` and `Tournaments` are behavioral fact tables; one user can have many rows per day.
- `Deposits` and `Withdrawals` are financial fact tables; each row represents one transaction.
- `Status` distinguishes successful vs failed transactions and should be retained during aggregation.
- The final Q1 table should be built at `UserID + ActivityDate` grain, after daily aggregation of each fact table.
