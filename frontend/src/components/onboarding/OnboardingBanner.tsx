"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useOnboardingStore, ONBOARDING_STEPS } from "@/store/onboarding";
import { TourBanner } from "./TourBanner";

export function OnboardingBanner() {
  const router = useRouter();
  const { isActive, currentStep, goTo, finish } = useOnboardingStore();

  useEffect(() => {
    if (!isActive) return;
    router.push(ONBOARDING_STEPS[currentStep].route);
  }, [isActive, currentStep]);

  const isLast = currentStep === ONBOARDING_STEPS.length - 1;

  function handleNext() {
    if (isLast) {
      finish();
      router.push("/chat");
    } else {
      goTo(currentStep + 1);
    }
  }

  return (
    <TourBanner
      label="Getting Started"
      steps={ONBOARDING_STEPS}
      currentStep={currentStep}
      isActive={isActive}
      isLast={isLast}
      onGoTo={goTo}
      onNext={handleNext}
      onDismiss={finish}
      lastLabel="Go to chat"
    />
  );
}
