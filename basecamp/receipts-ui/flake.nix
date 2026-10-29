{
  description = "Claim Receipts UI: QML frontend for the receipts core module";

  inputs = {
    logos-module-builder.url = "github:logos-co/logos-module-builder";
    # Placeholder — override with the sibling source at build time:
    #   nix build --override-input receipts path:../receipts-core '.#lgx-portable'
    # Once you publish the core module, replace this URL with the github
    # repo + dir syntax, e.g.:
    #   receipts.url = "github:<org>/<repo>?dir=receipts-core";
    receipts.url = "github:logos-co/logos-module-builder";
  };

  outputs = inputs@{ logos-module-builder, ... }:
    logos-module-builder.lib.mkLogosQmlModule {
      src = ./.;
      configFile = ./metadata.json;
      flakeInputs = inputs;
    };
}
