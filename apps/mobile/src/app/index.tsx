import { Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Stack } from "expo-router";

// Placeholder home screen. The feed, composer, and Bearer-token auth are
// built in M5 against @ramanhub/api-client (see PRODUCT_STATUS.md).
export default function Index() {
  return (
    <SafeAreaView className="bg-background">
      <Stack.Screen options={{ title: "Spectra Insight" }} />
      <View className="bg-background h-full w-full items-center justify-center p-4">
        <Text className="text-foreground text-3xl font-bold">
          Spectra<Text className="text-primary">Insight</Text>
        </Text>
        <Text className="text-muted-foreground mt-2">
          Mobile app scaffold — feed lands in M5.
        </Text>
      </View>
    </SafeAreaView>
  );
}
